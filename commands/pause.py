def setup_pause(bot, log):
    """
    Sets up the pause command.
    """
    
    @bot.command(name="pause")
    async def pause(ctx):
        """
        Pauses active playback if the bot is currently playing audio.
        """
        vc = ctx.voice_client
        if vc and vc.is_playing():
            vc.pause()
            log("Paused.", "info")
            await ctx.send("⏸️ Paused.")
        else:
            await ctx.send("❌ Nothing is playing.")