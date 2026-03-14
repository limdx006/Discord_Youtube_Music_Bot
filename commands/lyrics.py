import asyncio
import re

def setup_lyrics(bot, get_state, log, LYRICS_AVAILABLE):
    """
    Sets up the lyrics command.
    """
    
    @bot.command(name="lyrics", aliases=["ly"])
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
            # Import here to avoid issues if not available
            import syncedlyrics
            
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