import random
from collections import deque

def setup_shuffle(bot, get_state, log, prefetch_next):
    """
    Sets up the shuffle command.
    """
    
    @bot.command(name="shuffle", aliases=["sh"])
    async def shuffle(ctx):
        """
        Randomly shuffle the current queue.
        """
        state = get_state(ctx.guild.id)
        if len(state["queue"]) < 2:
            return await ctx.send("❌ Need at least 2 songs in the queue to shuffle.")
        q_list = list(state["queue"])
        random.shuffle(q_list)
        state["queue"] = deque(q_list)
        prefetch_next(ctx.guild.id)
        log(f"Queue shuffled ({len(q_list)} songs).", "info")
        await ctx.send(f"🔀 Shuffled **{len(q_list)} songs** in the queue!")