def setup_volume(bot, get_state, log):
    """
    Sets up the volume command.
    """
    
    @bot.command(name="volume", aliases=["vol", "v"])
    async def volume(ctx, vol: int):
        """
        Validates and applies a 0–100 volume level to both the guild state and the live audio source.
        """
        if not 0 <= vol <= 100:
            return await ctx.send("❌ Volume must be 0–100.")
        state = get_state(ctx.guild.id)
        state["volume"] = vol / 100
        vc = ctx.voice_client
        if vc and vc.source:
            vc.source.volume = state["volume"]
        log(f"Volume set to {vol}%", "info")
        await ctx.send(f"🔊 Volume: **{vol}%**")