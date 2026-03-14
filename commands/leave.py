def setup_leave(bot, get_state, log):
    """
    Sets up the leave command.
    """
    
    @bot.command(name="leave", aliases=["disconnect", "dc"])
    async def leave(ctx):
        """
        Clears state and disconnects the bot from the voice channel.
        """
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