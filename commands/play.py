import asyncio
import yt_dlp


def setup_play(
    bot, get_state, log, play_next, fetch_info, fetch_playlist, PREFIX, YDL_OPTS
):
    """
    Sets up the play command.
    """

    @bot.command(name="play", aliases=["p"])
    async def play(ctx, *, query: str):
        """
        Joins the caller's voice channel, fetches audio info, and queues or immediately plays the track.
        """
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
                return await ctx.send(
                    "❌ Could not load playlist. Make sure it's public."
                )
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
