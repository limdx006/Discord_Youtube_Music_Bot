def setup_resume(bot, log):
    """
    Sets up the resume command.
    """
    
    @bot.command(name="resume", aliases=["r"])
    async def resume(ctx):
        """
        Resumes playback if the bot is currently paused.
        """
        vc = ctx.voice_client
        if vc and vc.is_paused():
            vc.resume()
            log("Resumed.", "info")
            await ctx.send("▶️ Resumed.")
        else:
            await ctx.send("❌ Nothing is paused.")