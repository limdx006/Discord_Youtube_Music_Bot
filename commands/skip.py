def setup_skip(bot, log):
    """
    Sets up the skip command.
    """

    @bot.command(name="skip", aliases=["s", "next"])
    async def skip(ctx):
        """
        Stops the current track so the after_play callback can advance to the next queued song.
        """
        vc = ctx.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            log("Skipped.", "info")
            await ctx.send("⏭️ Skipped!")
        else:
            await ctx.send("❌ Nothing is playing.")
