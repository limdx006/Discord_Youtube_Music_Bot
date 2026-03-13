"""
================================================================================
  Discord Music Bot — Plays YouTube audio in your voice channel
================================================================================

COMMANDS:
  !play <youtube url or search term>   — play or add to queue
  !skip                                — skip current song
  !queue                               — show the queue
  !pause                               — pause playback
  !resume                              — resume playback
  !volume <0-100>                      — set volume
  !stop                                — stop and clear queue
  !leave                               — kick bot from voice channel
  !lyrics [song name]                  — show lyrics (current song or search)
================================================================================
"""

import tkinter as tk
from tkinter import scrolledtext, messagebox
import threading
import asyncio
import sys
import io
import queue
import datetime
import os
import re
from bot_token import (
    BOT_TOKEN,
)  # Import the bot token from a separate file for security

# ── Colour palette (dark Discord-style) ──────────────────────────────────────
BG = "#1e1f22"
BG2 = "#2b2d31"
BG3 = "#313338"
ACCENT = "#5865f2"  # Discord blurple
GREEN = "#57f287"
RED = "#ed4245"
YELLOW = "#fee75c"
TEXT = "#dbdee1"
TEXT_DIM = "#80848e"
FONT_MONO = ("Consolas", 10)
FONT_UI = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_BIG = ("Segoe UI", 13, "bold")

# ── Log queue (thread-safe bridge bot→GUI) ────────────────────────────────────
log_q = queue.Queue()


def log(msg: str, tag: str = "info"):
    # Timestamps a message and puts it on the thread-safe log queue with a severity tag
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    log_q.put((f"[{ts}] {msg}", tag))


# ── Redirect stdout/stderr into our log ──────────────────────────────────────
class StreamRedirect(io.TextIOBase):
    def __init__(self, tag="stdout"):
        self.tag = tag
        self.buf = ""

    def write(self, s):
        # Strips and forwards non-empty text to the log queue under the assigned tag
        if s and s.strip():
            log(s.strip(), self.tag)
        return len(s)

    def flush(self):
        # No-op flush required by TextIOBase interface
        pass


# ── Import bot code inline so we can control the event loop ──────────────────
import discord
from discord.ext import commands
import yt_dlp
from collections import deque

# Import syncedlyrics for lyrics functionality
try:
    import syncedlyrics

    LYRICS_AVAILABLE = True
except ImportError:
    LYRICS_AVAILABLE = False
    log(
        "syncedlyrics not installed. Lyrics feature will be disabled. Install with: pip install syncedlyrics",
        "warn",
    )

PREFIX = "!"
VOLUME = 0.5

YDL_OPTS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "noplaylist": True,
}

# Separate opts for playlist extraction — allows multiple entries
YDL_PLAYLIST_OPTS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "noplaylist": False,  # allow playlists
    "extract_flat": "in_playlist",  # fast: get metadata without downloading each stream URL yet
}
FFMPEG_OPTS = {
    # Reconnect on drop; large probesize/analyzeduration prevents slow start stutter
    "before_options": (
        "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
        "-probesize 200M -analyzeduration 0"
    ),
    "options": "-vn -bufsize 512k",
}

intents = discord.Intents.none()
intents.guilds = True
intents.voice_states = True
intents.guild_messages = True
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)
guild_state = {}


def get_state(guild_id):
    # Returns the per-guild state dict, creating it with defaults if it doesn't exist yet
    if guild_id not in guild_state:
        guild_state[guild_id] = {
            "queue": deque(),
            "volume": VOLUME,
            "current_song": None,
            "prefetched": None,  # next track with stream URL already resolved
        }
    return guild_state[guild_id]


async def fetch_info(query):
    # Runs yt-dlp in a thread executor to extract video info for a URL or search query without blocking
    loop = asyncio.get_event_loop()
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        try:
            info = await loop.run_in_executor(
                None, lambda: ydl.extract_info(query, download=False)
            )
            if "entries" in info:
                info = info["entries"][0]
            return info
        except Exception as e:
            log(f"yt-dlp error: {e}", "error")
            return None


async def fetch_playlist(url: str) -> list:
    """Extract all video entries from a YouTube/YT Music playlist URL."""
    loop = asyncio.get_event_loop()
    with yt_dlp.YoutubeDL(YDL_PLAYLIST_OPTS) as ydl:
        try:
            info = await loop.run_in_executor(
                None, lambda: ydl.extract_info(url, download=False)
            )
            if not info:
                return []
            entries = info.get("entries", [])
            # Build minimal track dicts — stream URL fetched lazily when each song plays
            tracks = []
            for e in entries:
                if not e:
                    continue
                vid_id = e.get("id") or e.get("url", "")
                webpage = e.get("url") or f"https://www.youtube.com/watch?v={vid_id}"
                tracks.append(
                    {
                        "title": e.get("title", "Unknown"),
                        "duration": e.get("duration", 0),
                        "webpage_url": webpage,
                        "url": webpage,  # will be resolved to stream URL in play_next
                        "_needs_resolve": True,  # flag: stream URL not yet fetched
                    }
                )
            return tracks
        except Exception as e:
            log(f"Playlist fetch error: {e}", "error")
            return []


async def resolve_stream(info: dict) -> dict:
    """Resolve the real stream URL for a track that only has a webpage URL."""
    if not info.get("_needs_resolve"):
        return info
    loop = asyncio.get_event_loop()
    try:
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            fresh = await loop.run_in_executor(
                None, lambda: ydl.extract_info(info["webpage_url"], download=False)
            )
            if fresh and "entries" in fresh:
                fresh = fresh["entries"][0]
            if fresh:
                info["url"] = fresh.get("url", info["url"])
                info["title"] = info.get("title") or fresh.get("title", "Unknown")
                info["duration"] = info.get("duration") or fresh.get("duration", 0)
                info["_needs_resolve"] = False
    except Exception as e:
        log(f"Stream resolve error: {e}", "error")
    return info


def prefetch_next(guild_id: int):
    """Fire-and-forget: resolve stream URL of the next queued track in background."""
    state = get_state(guild_id)
    q = state["queue"]
    if not q:
        return
    nxt = q[0]  # peek, don't pop
    if not nxt.get("_needs_resolve"):
        return  # already resolved or plain search result

    async def _do_prefetch():
        resolved = await resolve_stream(dict(nxt))
        # Write resolved fields back into the actual queue entry
        nxt.update(resolved)
        state["prefetched"] = nxt
        log(f"Prefetched: {nxt.get('title', '?')}", "info")

    asyncio.run_coroutine_threadsafe(_do_prefetch(), bot.loop)


def make_source(url, volume):
    # Wraps a streaming FFmpeg audio source in a volume transformer at the given level
    source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTS)
    return discord.PCMVolumeTransformer(source, volume=volume)


def play_next(guild_id, vc, ctx):
    """Dequeue and play the next track. Stream URL must already be resolved."""
    state = get_state(guild_id)
    if not state["queue"]:
        asyncio.run_coroutine_threadsafe(ctx.send("✅ Queue finished!"), bot.loop)
        log("Queue finished.", "success")
        state["current_song"] = None
        return

    info = state["queue"].popleft()
    state["prefetched"] = None

    # If still unresolved (shouldn't happen with prefetch, but fallback via async)
    if info.get("_needs_resolve"):
        log(
            f"Stream not prefetched yet for '{info.get('title')}', resolving now...",
            "warn",
        )

        async def _resolve_then_play():
            resolved = await resolve_stream(info)
            _start_playback(guild_id, vc, ctx, resolved)

        asyncio.run_coroutine_threadsafe(_resolve_then_play(), bot.loop)
        return

    _start_playback(guild_id, vc, ctx, info)


def _start_playback(guild_id, vc, ctx, info):
    """Actually start playing a fully-resolved track and kick off prefetch of the next one."""
    state = get_state(guild_id)
    url = info["url"]

    state["current_song"] = {
        "title": info.get("title", "Unknown"),
        "artist": info.get("artist", info.get("channel", "Unknown Artist")),
        "duration": info.get("duration", 0),
    }

    def after_play(error):
        if error:
            log(f"Player error: {error}", "error")
        play_next(guild_id, vc, ctx)

    source = make_source(url, state["volume"])
    vc.play(source, after=after_play)

    duration = info.get("duration", 0)
    mins, secs = divmod(int(duration), 60)
    title = info.get("title", "?")
    log(f"Now playing: {title} [{mins}:{secs:02d}]", "success")
    asyncio.run_coroutine_threadsafe(
        ctx.send(f"🎵 Now playing: **{title}** `[{mins}:{secs:02d}]`"), bot.loop
    )

    # Kick off background prefetch of the NEXT track so it's ready instantly
    prefetch_next(guild_id)


@bot.event
async def on_ready():
    # Fires once the bot has connected to Discord and logs its identity and guild count
    log(f"Logged in as {bot.user}", "success")
    log(f"Prefix: {PREFIX}   |   Serving {len(bot.guilds)} server(s)", "info")


@bot.event
async def on_command_error(ctx, error):
    # Silently ignores unknown commands and logs/reports all other errors back to the channel
    if isinstance(error, commands.CommandNotFound):
        return
    log(f"Command error: {error}", "error")
    await ctx.send(f"⚠️ Error: {error}")


@bot.command(name="play", aliases=["p"])
async def play(ctx, *, query: str):
    # Joins the caller's voice channel, fetches audio info, and queues or immediately plays the track
    if not ctx.author.voice:
        return await ctx.send("❌ Join a voice channel first!")
    vc = ctx.voice_client
    if vc is None:
        vc = await ctx.author.voice.channel.connect()
    elif vc.channel != ctx.author.voice.channel:
        await vc.move_to(ctx.author.voice.channel)
    state = get_state(ctx.guild.id)

    # ── Playlist detection ────────────────────────────────────────────────────
    is_playlist = (
        "list=" in query or "playlist" in query.lower()
    ) and query.startswith("http")

    if is_playlist:
        await ctx.send(f"📋 Loading playlist, please wait...")
        log(f"Loading playlist: {query}", "info")
        tracks = await fetch_playlist(query)
        if not tracks:
            return await ctx.send("❌ Could not load playlist. Make sure it's public.")
        for t in tracks:
            state["queue"].append(t)
        log(f"Playlist loaded: {len(tracks)} tracks queued.", "success")
        await ctx.send(f"✅ Added **{len(tracks)} songs** from playlist to queue!")
        if not vc.is_playing() and not vc.is_paused():
            play_next(ctx.guild.id, vc, ctx)
        return

    # ── Single track ──────────────────────────────────────────────────────────
    log(f"Searching: {query}", "info")
    await ctx.send(f"🔍 Searching: **{query}**...")
    info = await fetch_info(query)
    if not info:
        return await ctx.send("❌ Could not find that video.")
    title = info.get("title", "Unknown")
    duration = info.get("duration", 0)
    webpage = info.get("webpage_url", "")
    if webpage:
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            fresh = await loop.run_in_executor(
                None, lambda: ydl.extract_info(webpage, download=False)
            )
            if fresh and "entries" in fresh:
                fresh = fresh["entries"][0]
            if fresh:
                fresh["title"] = title
                fresh["duration"] = duration
                info = fresh
    mins, secs = divmod(int(duration), 60)
    if vc.is_playing() or vc.is_paused():
        state["queue"].append(info)
        log(f"Queued #{len(state['queue'])}: {title}", "info")
        await ctx.send(
            f"➕ Added to queue (#{len(state['queue'])}): **{title}** `[{mins}:{secs:02d}]`"
        )
    else:
        state["queue"].append(info)
        play_next(ctx.guild.id, vc, ctx)


@bot.command(name="skip", aliases=["s", "next"])
async def skip(ctx):
    # Stops the current track so the after_play callback can advance to the next queued song
    vc = ctx.voice_client
    if vc and (vc.is_playing() or vc.is_paused()):
        vc.stop()
        log("Skipped.", "info")
        await ctx.send("⏭️ Skipped!")
    else:
        await ctx.send("❌ Nothing is playing.")


@bot.command(name="queue", aliases=["q"])
async def show_queue(ctx):
    # Displays up to 10 upcoming tracks with their durations, plus a count of remaining songs
    state = get_state(ctx.guild.id)
    if not state["queue"]:
        return await ctx.send("📭 Queue is empty.")
    lines = [f"**Up next ({len(state['queue'])} songs):**"]
    for i, info in enumerate(list(state["queue"])[:10], 1):
        d = info.get("duration", 0)
        m, s = divmod(int(d), 60)
        lines.append(f"  `{i}.` {info['title']} `[{m}:{s:02d}]`")
    if len(state["queue"]) > 10:
        lines.append(f"  _...and {len(state['queue'])-10} more_")
    await ctx.send("\n".join(lines))


@bot.command(name="pause")
async def pause(ctx):
    # Pauses active playback if the bot is currently playing audio
    vc = ctx.voice_client
    if vc and vc.is_playing():
        vc.pause()
        log("Paused.", "info")
        await ctx.send("⏸️ Paused.")
    else:
        await ctx.send("❌ Nothing is playing.")


@bot.command(name="resume", aliases=["r"])
async def resume(ctx):
    # Resumes playback if the bot is currently paused
    vc = ctx.voice_client
    if vc and vc.is_paused():
        vc.resume()
        log("Resumed.", "info")
        await ctx.send("▶️ Resumed.")
    else:
        await ctx.send("❌ Nothing is paused.")


@bot.command(name="volume", aliases=["vol", "v"])
async def volume(ctx, vol: int):
    # Validates and applies a 0–100 volume level to both the guild state and the live audio source
    if not 0 <= vol <= 100:
        return await ctx.send("❌ Volume must be 0–100.")
    state = get_state(ctx.guild.id)
    state["volume"] = vol / 100
    vc = ctx.voice_client
    if vc and vc.source:
        vc.source.volume = state["volume"]
    log(f"Volume set to {vol}%", "info")
    await ctx.send(f"🔊 Volume: **{vol}%**")


@bot.command(name="stop")
async def stop(ctx):
    # Clears the queue and current song state, then halts playback immediately
    state = get_state(ctx.guild.id)
    state["queue"].clear()
    state["current_song"] = None
    vc = ctx.voice_client
    if vc and (vc.is_playing() or vc.is_paused()):
        vc.stop()
        log("Stopped and queue cleared.", "info")
        await ctx.send("⏹️ Stopped.")
    else:
        await ctx.send("❌ Nothing is playing.")


@bot.command(name="leave", aliases=["disconnect", "dc"])
async def leave(ctx):
    # Clears state and disconnects the bot from the voice channel
    state = get_state(ctx.guild.id)
    state["queue"].clear()
    state["current_song"] = None
    vc = ctx.voice_client
    if vc:
        await vc.disconnect()
        log("Disconnected from voice.", "info")
        await ctx.send("👋 Disconnected.")
    else:
        await ctx.send("❌ Not in a voice channel.")


@bot.command(name="nowplaying", aliases=["np"])
async def nowplaying(ctx):
    # Reports whether audio is currently playing and hints users toward the queue command
    vc = ctx.voice_client
    if vc and vc.is_playing():
        await ctx.send("🎵 Currently playing! Use `!queue` to see what's next.")
    else:
        await ctx.send("❌ Nothing is playing.")


# ── NEW: LYRICS COMMAND ───────────────────────────────────────────────────────


@bot.command(name="lyrics", aliases=["ly", "l"])
async def lyrics(ctx, *, query: str = None):
    """
    Fetch and display lyrics for the currently playing song or a specific search query.
    Usage: !lyrics (for current song) or !lyrics <song name>
    """
    if not LYRICS_AVAILABLE:
        return await ctx.send(
            "❌ Lyrics feature is not available. Install syncedlyrics: `pip install syncedlyrics`"
        )

    state = get_state(ctx.guild.id)
    search_term = None

    # Determine what to search for
    if query:
        # User provided a search term
        search_term = query
        log(f"Searching lyrics for: {search_term}", "info")
    else:
        # Try to get current song info
        if state.get("current_song"):
            song_info = state["current_song"]
            # Try to extract artist from title (common YouTube format: "Artist - Title")
            title = song_info["title"]
            search_term = title
            log(f"Fetching lyrics for current song: {search_term}", "info")
        else:
            return await ctx.send(
                "❌ No song is currently playing. Use `!lyrics <song name>` to search for a specific song."
            )

    # Send searching message
    msg = await ctx.send(f"🔍 Searching lyrics for **{search_term}**...")

    try:
        # Run syncedlyrics in executor to not block the event loop
        loop = asyncio.get_event_loop()

        def fetch_lyrics():
            # Calls syncedlyrics synchronously (run inside an executor to avoid blocking the event loop)
            try:
                # Search for lyrics (plain text, no timestamps for cleaner display)
                result = syncedlyrics.search(search_term, plain_only=True)
                return result
            except Exception as e:
                return str(e)

        lyrics_result = await loop.run_in_executor(None, fetch_lyrics)

        if not lyrics_result:
            await msg.edit(content=f"❌ No lyrics found for **{search_term}**.")
            return

        if isinstance(lyrics_result, str) and lyrics_result.startswith("Error"):
            await msg.edit(content=f"❌ Error fetching lyrics: {lyrics_result}")
            return

        # Clean up lyrics (remove excessive newlines, timestamps if any slipped through)
        lyrics_clean = re.sub(
            r"\[(\d{2}:\d{2}\.\d{2})\]", "", lyrics_result
        )  # Remove LRC timestamps
        lyrics_clean = re.sub(
            r"\n{3,}", "\n\n", lyrics_clean
        )  # Normalize excessive newlines

        # Split lyrics into chunks if too long (Discord limit ~2000 chars)
        max_length = 1900
        chunks = []

        if len(lyrics_clean) <= max_length:
            chunks = [lyrics_clean]
        else:
            # Split by paragraphs to keep context
            paragraphs = lyrics_clean.split("\n\n")
            current_chunk = ""

            for para in paragraphs:
                if len(current_chunk) + len(para) + 2 <= max_length:
                    current_chunk += para + "\n\n"
                else:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    current_chunk = para + "\n\n"

            if current_chunk:
                chunks.append(current_chunk.strip())

            # If still too long, force split
            if not chunks:
                for i in range(0, len(lyrics_clean), max_length):
                    chunks.append(lyrics_clean[i : i + max_length])

        # Edit original message with first chunk
        header = f"🎤 **Lyrics for:** {search_term}\n"
        footer = f"\n\n*Page 1/{len(chunks)}*" if len(chunks) > 1 else ""

        await msg.edit(
            content=f"{header}```{chunks[0][:max_length-len(header)-len(footer)-6]}```{footer}"
        )

        # Send additional chunks if needed
        for i, chunk in enumerate(chunks[1:], 2):
            footer = f"\n\n*Page {i}/{len(chunks)}*"
            await ctx.send(f"```{chunk[:max_length-len(footer)-6]}```{footer}")

        log(f"Lyrics sent for: {search_term} ({len(chunks)} page(s))", "success")

    except Exception as e:
        log(f"Lyrics error: {e}", "error")
        await msg.edit(content=f"❌ Failed to fetch lyrics: {str(e)}")


# ── GUI ───────────────────────────────────────────────────────────────────────


class BotLauncher(tk.Tk):
    def __init__(self):
        # Initialises the Tkinter window, sets up bot state variables, and wires up UI and log polling
        super().__init__()
        self.title("🎵 Discord Music Bot")
        self.geometry("720x520")
        self.minsize(600, 400)
        self.configure(bg=BG)
        self.resizable(True, True)

        self.bot_thread = None
        self.bot_loop = None
        self.is_running = False

        self._build_ui()
        self._poll_logs()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        # Constructs the header bar, scrollable log area, and bottom control bar with all widgets
        # ── Header bar ────────────────────────────────────────────────────────
        header = tk.Frame(self, bg=ACCENT, height=48)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(
            header, text="🎵  Discord Music Bot", font=FONT_BIG, fg="white", bg=ACCENT
        ).pack(side="left", padx=16, pady=10)

        self.status_dot = tk.Label(
            header, text="●", font=("Segoe UI", 14), fg=TEXT_DIM, bg=ACCENT
        )
        self.status_dot.pack(side="right", padx=6)
        self.status_lbl = tk.Label(
            header, text="Offline", font=FONT_UI, fg=TEXT_DIM, bg=ACCENT
        )
        self.status_lbl.pack(side="right", padx=2)

        # ── Log area ──────────────────────────────────────────────────────────
        log_frame = tk.Frame(self, bg=BG2, padx=2, pady=2)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(10, 4))

        self.log_box = scrolledtext.ScrolledText(
            log_frame,
            bg=BG3,
            fg=TEXT,
            font=FONT_MONO,
            relief="flat",
            bd=0,
            wrap="word",
            insertbackground=TEXT,
            selectbackground=ACCENT,
            state="disabled",
        )
        self.log_box.pack(fill="both", expand=True)

        # colour tags
        self.log_box.tag_config("success", foreground=GREEN)
        self.log_box.tag_config("error", foreground=RED)
        self.log_box.tag_config("warn", foreground=YELLOW)
        self.log_box.tag_config("info", foreground=TEXT)
        self.log_box.tag_config("stdout", foreground=TEXT_DIM)
        self.log_box.tag_config("dim", foreground=TEXT_DIM)

        # ── Bottom bar ────────────────────────────────────────────────────────
        bar = tk.Frame(self, bg=BG2, pady=8)
        bar.pack(fill="x", padx=10, pady=(0, 10))

        self.start_btn = tk.Button(
            bar,
            text="▶  Start Bot",
            font=FONT_BOLD,
            bg=ACCENT,
            fg="white",
            activebackground="#4752c4",
            activeforeground="white",
            relief="flat",
            bd=0,
            padx=20,
            pady=6,
            cursor="hand2",
            command=self._toggle_bot,
        )
        self.start_btn.pack(side="left", padx=(6, 4))

        tk.Button(
            bar,
            text="🗑  Clear Log",
            font=FONT_UI,
            bg=BG3,
            fg=TEXT_DIM,
            activebackground=BG,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            padx=14,
            pady=6,
            cursor="hand2",
            command=self._clear_log,
        ).pack(side="left", padx=4)

        # cmd count
        self.cmd_var = tk.StringVar(value="Commands: 0")
        tk.Label(
            bar, textvariable=self.cmd_var, font=FONT_UI, fg=TEXT_DIM, bg=BG2
        ).pack(side="right", padx=10)

        self.cmd_count = 0

        self._append_log("Welcome! Press ▶ Start Bot to connect.", "dim")
        self._append_log(
            f"Token: {'set ✓' if BOT_TOKEN != 'PASTE_YOUR_TOKEN_HERE' else '⚠ not set — edit bot_launcher.py'}",
            "success" if BOT_TOKEN != "PASTE_YOUR_TOKEN_HERE" else "error",
        )

        # Check lyrics availability
        if LYRICS_AVAILABLE:
            self._append_log(
                "Lyrics feature: Available ✓ (syncedlyrics loaded)", "success"
            )
        else:
            self._append_log(
                "Lyrics feature: Unavailable ✗ (pip install syncedlyrics)", "warn"
            )

    def _append_log(self, msg: str, tag: str = "info"):
        # Appends a coloured log line to the scrolled text box and increments the command counter for play events
        self.log_box.config(state="normal")
        self.log_box.insert("end", msg + "\n", tag)
        self.log_box.see("end")
        self.log_box.config(state="disabled")
        if tag in ("info", "success") and "playing" in msg.lower():
            self.cmd_count += 1
            self.cmd_var.set(f"Commands: {self.cmd_count}")

    def _clear_log(self):
        # Wipes all text from the log box widget
        self.log_box.config(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.config(state="disabled")

    def _poll_logs(self):
        # Drains all pending messages from the thread-safe log queue into the GUI, then reschedules itself every 100 ms
        try:
            while True:
                msg, tag = log_q.get_nowait()
                self._append_log(msg, tag)
        except queue.Empty:
            pass
        self.after(100, self._poll_logs)

    def _set_status(self, online: bool):
        # Updates the status indicator dot, label, and start/stop button to reflect the bot's current connection state
        if online:
            self.status_dot.config(fg=GREEN)
            self.status_lbl.config(text="Online", fg=GREEN)
            self.start_btn.config(
                text="⏹  Stop Bot", bg=RED, activebackground="#c03537"
            )
        else:
            self.status_dot.config(fg=TEXT_DIM)
            self.status_lbl.config(text="Offline", fg=TEXT_DIM)
            self.start_btn.config(
                text="▶  Start Bot", bg=ACCENT, activebackground="#4752c4"
            )

    def _toggle_bot(self):
        # Routes the start/stop button press to the appropriate action based on current running state
        if self.is_running:
            self._stop_bot()
        else:
            self._start_bot()

    def _start_bot(self):
        # Validates the token, redirects stdout/stderr to the GUI log, and launches the bot in a daemon thread
        if BOT_TOKEN == "PASTE_YOUR_TOKEN_HERE":
            messagebox.showerror(
                "No Token", "Please paste your bot token into bot_launcher.py"
            )
            return

        self.is_running = True
        self._set_status(True)
        log("Starting bot...", "info")

        # Redirect stdout/stderr
        sys.stdout = StreamRedirect("stdout")
        sys.stderr = StreamRedirect("error")

        def run():
            # Creates a dedicated asyncio event loop for the bot and runs it until stopped or it errors out
            self.bot_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.bot_loop)
            try:
                self.bot_loop.run_until_complete(bot.start(BOT_TOKEN))
            except asyncio.CancelledError:
                pass
            except Exception as e:
                log(f"Bot error: {e}", "error")
            finally:
                self.is_running = False
                self.after(0, lambda: self._set_status(False))
                log("Bot stopped.", "warn")

        self.bot_thread = threading.Thread(target=run, daemon=True)
        self.bot_thread.start()

    def _stop_bot(self):
        # Schedules a graceful bot shutdown on its event loop and updates the GUI status to offline
        log("Stopping bot...", "warn")
        if self.bot_loop and not self.bot_loop.is_closed():
            asyncio.run_coroutine_threadsafe(bot.close(), self.bot_loop)
        self.is_running = False
        self._set_status(False)

    def _on_close(self):
        # Stops the bot if running before closing the window to ensure a clean shutdown
        if self.is_running:
            self._stop_bot()
        self.destroy()


if __name__ == "__main__":
    app = BotLauncher()
    app.mainloop()
