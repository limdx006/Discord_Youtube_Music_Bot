def setup_queue(bot, get_state):
    """
    Sets up the queue command.
    """
    
    @bot.command(name="queue", aliases=["q"])
    async def show_queue(ctx):
        """
        Displays up to 10 upcoming tracks with their durations, plus a count of remaining songs.
        """
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