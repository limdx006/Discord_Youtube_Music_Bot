def setup_stop(bot, get_state, log):
    """
    Sets up the stop command.
    """
    
    @bot.command(name="stop")
    async def stop(ctx):
        """
        Clears the queue and current song state, then halts playback immediately.
        """
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