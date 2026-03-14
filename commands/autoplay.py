import asyncio

def setup_autoplay(bot, get_state, log):
    """
    Sets up the autoplay command.
    """
    
    @bot.command(name="autoplay", aliases=["ap", "radio", "auto"])
    async def autoplay(ctx):
        """
        Toggle autoplay mode — bot keeps queuing related songs when queue runs out.
        """
        state = get_state(ctx.guild.id)
        state["autoplay"] = not state.get("autoplay", False)
        if state["autoplay"]:
            log("Autoplay ON.", "success")
            await ctx.send(
                "🔁 **Autoplay ON** — I'll keep queuing related songs when the queue runs out."
                "Use `!autoplay` again to turn it off."
            )
        else:
            log("Autoplay OFF.", "info")
            await ctx.send("⏹️ **Autoplay OFF** — queue will stop when empty.")