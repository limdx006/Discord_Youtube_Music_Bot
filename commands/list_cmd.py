# commands/list_cmd.py
import discord
from discord.ext import commands
import json
import os
import asyncio
from collections import deque

# File to store user lists
LISTS_FILE = "user_lists.json"

def load_lists():
    """Load user lists from JSON file."""
    if os.path.exists(LISTS_FILE):
        with open(LISTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_lists(lists_data):
    """Save user lists to JSON file."""
    with open(LISTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(lists_data, f, indent=2, ensure_ascii=False)

def get_user_lists(user_id):
    """Get all lists for a specific user."""
    all_lists = load_lists()
    return all_lists.get(str(user_id), {})

def save_user_lists(user_id, user_lists):
    """Save lists for a specific user."""
    all_lists = load_lists()
    all_lists[str(user_id)] = user_lists
    save_lists(all_lists)

def is_yes(response):
    """Check if response is yes."""
    return response.lower() in ['y', 'yes']

def is_no(response):
    """Check if response is no."""
    return response.lower() in ['n', 'no']

def setup_list(bot, get_state, log, play_next, fetch_info, PREFIX):
    """
    Sets up the list command for custom user playlists.
    """
    
    @bot.group(name="list", aliases=["pl", "playlist"], invoke_without_command=True)
    async def list_group(ctx, list_name: str = None):
        """
        Manage custom song lists. Use !list <name> to view, or subcommands to manage.
        """
        if list_name is None:
            # Show all user's lists
            user_lists = get_user_lists(ctx.author.id)
            if not user_lists:
                return await ctx.send("📭 You don't have any lists yet. Create one with `!list create <name>`")
            
            embed = discord.Embed(
                title=f"🎵 {ctx.author.display_name}'s Lists",
                color=0x5865f2
            )
            
            for name, songs in user_lists.items():
                total_duration = sum(song.get('duration', 0) for song in songs)
                mins, secs = divmod(int(total_duration), 60)
                embed.add_field(
                    name=f"📋 {name}",
                    value=f"{len(songs)} songs • Total: {mins}:{secs:02d}",
                    inline=True
                )
            
            embed.set_footer(text=f"Use {PREFIX}list <name> to view songs • {PREFIX}list play <name> to play")
            return await ctx.send(embed=embed)
        
        # Show specific list contents
        user_lists = get_user_lists(ctx.author.id)
        if list_name not in user_lists:
            return await ctx.send(f"❌ List `{list_name}` not found. Use `!list create {list_name}` to create it.")
        
        songs = user_lists[list_name]
        if not songs:
            return await ctx.send(f"📭 List `{list_name}` is empty. Add songs with `!list add <song>`")
        
        # Build song list display
        lines = [f"**📋 {list_name} ({len(songs)} songs):**"]
        for i, song in enumerate(songs[:15], 1):
            d = song.get('duration', 0)
            m, s = divmod(int(d), 60)
            lines.append(f"  `{i}.` {song['title']} `[{m}:{s:02d}]`")
        
        if len(songs) > 15:
            lines.append(f"  _...and {len(songs)-15} more_")
        
        total_duration = sum(song.get('duration', 0) for song in songs)
        mins, secs = divmod(int(total_duration), 60)
        lines.append(f"\n**Total duration:** `{mins}:{secs:02d}`")
        
        await ctx.send("\n".join(lines))
    
    @list_group.command(name="create")
    async def list_create(ctx, *, list_name: str):
        """Create a new empty list."""
        if not list_name or len(list_name) > 50:
            return await ctx.send("❌ List name must be 1-50 characters.")
        
        # Sanitize list name
        list_name = list_name.strip()
        
        user_lists = get_user_lists(ctx.author.id)
        
        if list_name in user_lists:
            return await ctx.send(f"❌ List `{list_name}` already exists.")
        
        user_lists[list_name] = []
        save_user_lists(ctx.author.id, user_lists)
        
        log(f"User {ctx.author} created list: {list_name}", "info")
        await ctx.send(f"✅ Created list: **{list_name}**\nAdd songs with `!list add <song>` or `!list add` to add current song.")
    
    @list_group.command(name="delete")
    async def list_delete(ctx, *, list_name: str):
        """Delete a list."""
        user_lists = get_user_lists(ctx.author.id)
        
        if list_name not in user_lists:
            return await ctx.send(f"❌ List `{list_name}` not found.")
        
        song_count = len(user_lists[list_name])
        
        # Confirmation with text input
        prompt = await ctx.send(f"⚠️ Delete list `{list_name}` with {song_count} songs?\nReply with **Y** (yes) or **N** (no)")
        
        def check(m):
            return (
                m.author.id == ctx.author.id and 
                m.channel.id == ctx.channel.id and 
                m.content.lower() in ['y', 'yes', 'n', 'no']
            )
        
        try:
            msg = await bot.wait_for('message', timeout=30.0, check=check)
            
            if is_yes(msg.content):
                del user_lists[list_name]
                save_user_lists(ctx.author.id, user_lists)
                log(f"User {ctx.author} deleted list: {list_name}", "info")
                await ctx.send(f"🗑️ Deleted list: **{list_name}**")
            else:
                await ctx.send("❌ Cancelled.")
                
        except asyncio.TimeoutError:
            await ctx.send("⏰ Timed out. Delete cancelled.")
    
    @list_group.command(name="add")
    async def list_add(ctx, *, query: str = None):
        """
        Add a song to a list. 
        Usage: !list add (adds current song) or !list add <song name/URL> (searches and adds)
        """
        user_lists = get_user_lists(ctx.author.id)
        
        if not user_lists:
            return await ctx.send(f"📭 You have no lists. Create one with `!list create <name>`")
        
        state = get_state(ctx.guild.id)
        
        # If no query, add current song
        if query is None:
            if not state.get("current_song"):
                return await ctx.send("❌ No song is currently playing. Provide a song name or URL.")
            
            current = state["current_song"]
            song_data = {
                "title": current["title"],
                "url": state.get("last_webpage", ""),
                "duration": current["duration"]
            }
            
            # Ask which list to add to
            list_names = list(user_lists.keys())
            if len(list_names) == 1:
                target_list = list_names[0]
                user_lists[target_list].append(song_data)
                save_user_lists(ctx.author.id, user_lists)
                return await ctx.send(f"➕ Added **{song_data['title']}** to list `{target_list}`")
            else:
                # Show list selection
                options = "\n".join([f"{i+1}. `{name}`" for i, name in enumerate(list_names)])
                prompt = await ctx.send(f"**Which list?** (reply with number)\n{options}")
                
                def check(m):
                    return m.author == ctx.author and m.channel == ctx.channel and m.content.isdigit()
                
                try:
                    msg = await bot.wait_for('message', timeout=30.0, check=check)
                    choice = int(msg.content) - 1
                    if choice < 0 or choice >= len(list_names):
                        return await ctx.send("❌ Invalid selection.")
                    target_list = list_names[choice]
                except asyncio.TimeoutError:
                    return await ctx.send("⏰ Timed out.")
            
            user_lists[target_list].append(song_data)
            save_user_lists(ctx.author.id, user_lists)
            
            log(f"Added current song to {ctx.author}'s list '{target_list}': {song_data['title']}", "info")
            return await ctx.send(f"➕ Added **{song_data['title']}** to list `{target_list}`")
        
        # Search for song
        await ctx.send(f"🔍 Searching: **{query}**...")
        info = await fetch_info(query)
        
        if not info:
            return await ctx.send("❌ Could not find that song.")
        
        # Show confirmation with text input
        title = info.get("title", "Unknown")
        duration = info.get("duration", 0)
        webpage = info.get("webpage_url", "")
        
        m, s = divmod(int(duration), 60)
        
        embed = discord.Embed(
            title="➕ Add this song?",
            description=f"**{title}** `[{m}:{s:02d}]`\n{webpage or 'N/A'}",
            color=0x5865f2
        )
        embed.set_footer(text="Reply with Y (yes) or N (no)")
        
        msg = await ctx.send(embed=embed)
        
        def check_yes_no(m):
            return (
                m.author.id == ctx.author.id and 
                m.channel.id == ctx.channel.id and 
                (is_yes(m.content) or is_no(m.content))
            )
        
        try:
            response = await bot.wait_for('message', timeout=30.0, check=check_yes_no)
            
            if is_yes(response.content):
                # Ask which list
                list_names = list(user_lists.keys())
                if len(list_names) == 1:
                    target_list = list_names[0]
                else:
                    options = "\n".join([f"{i+1}. `{name}`" for i, name in enumerate(list_names)])
                    await ctx.send(f"**Which list?** (reply with number)\n{options}")
                    
                    def check_list(m):
                        return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and m.content.isdigit()
                    
                    try:
                        list_msg = await bot.wait_for('message', timeout=30.0, check=check_list)
                        choice = int(list_msg.content) - 1
                        if choice < 0 or choice >= len(list_names):
                            return await ctx.send("❌ Invalid selection.")
                        target_list = list_names[choice]
                    except asyncio.TimeoutError:
                        return await ctx.send("⏰ Timed out.")
                
                song_data = {
                    "title": title,
                    "url": webpage,
                    "duration": duration
                }
                
                user_lists[target_list].append(song_data)
                save_user_lists(ctx.author.id, user_lists)
                
                await ctx.send(f"✅ Added **{title}** to list `{target_list}`")
                log(f"User {ctx.author} added to list '{target_list}': {title}", "info")
            else:
                await ctx.send("❌ Cancelled.")
                
        except asyncio.TimeoutError:
            await ctx.send("⏰ Timed out.")
    
    @list_group.command(name="remove")
    async def list_remove(ctx, list_name: str, *, song_query: str):
        """
        Remove a song from a list.
        Usage: !list remove <list_name> <song_number or song_name>
        """
        user_lists = get_user_lists(ctx.author.id)
        
        if list_name not in user_lists:
            return await ctx.send(f"❌ List `{list_name}` not found.")
        
        songs = user_lists[list_name]
        if not songs:
            return await ctx.send(f"📭 List `{list_name}` is empty.")
        
        # Try to parse as number first
        try:
            song_num = int(song_query)
            if 1 <= song_num <= len(songs):
                song = songs[song_num - 1]
                
                # Confirmation
                await ctx.send(f"Remove **{song['title']}** from `{list_name}`?\nReply with **Y** (yes) or **N** (no)")
                
                def check(m):
                    return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and m.content.lower() in ['y', 'yes', 'n', 'no']
                
                try:
                    msg = await bot.wait_for('message', timeout=30.0, check=check)
                    if is_yes(msg.content):
                        removed = songs.pop(song_num - 1)
                        save_user_lists(ctx.author.id, user_lists)
                        return await ctx.send(f"🗑️ Removed **{removed['title']}** from `{list_name}`")
                    else:
                        return await ctx.send("❌ Cancelled.")
                except asyncio.TimeoutError:
                    return await ctx.send("⏰ Timed out.")
            else:
                return await ctx.send(f"❌ Invalid song number. List has {len(songs)} songs.")
        except ValueError:
            pass
        
        # Search by name
        matches = [(i, s) for i, s in enumerate(songs) if song_query.lower() in s['title'].lower()]
        
        if not matches:
            return await ctx.send(f"❌ No songs matching `{song_query}` found in list.")
        
        if len(matches) == 1:
            idx, song = matches[0]
            
            # Confirmation
            await ctx.send(f"Remove **{song['title']}** from `{list_name}`?\nReply with **Y** (yes) or **N** (no)")
            
            def check(m):
                return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and m.content.lower() in ['y', 'yes', 'n', 'no']
            
            try:
                msg = await bot.wait_for('message', timeout=30.0, check=check)
                if is_yes(msg.content):
                    removed = songs.pop(idx)
                    save_user_lists(ctx.author.id, user_lists)
                    return await ctx.send(f"🗑️ Removed **{removed['title']}** from `{list_name}`")
                else:
                    return await ctx.send("❌ Cancelled.")
            except asyncio.TimeoutError:
                return await ctx.send("⏰ Timed out.")
        
        # Multiple matches - ask for clarification
        lines = [f"**Multiple matches found. Which one to remove?** (reply with number)\n"]
        for i, (idx, song) in enumerate(matches[:10], 1):
            d = song.get('duration', 0)
            m, s = divmod(int(d), 60)
            lines.append(f"{i}. `{song['title']}` `[{m}:{s:02d}]`")
        
        prompt = await ctx.send("\n".join(lines))
        
        def check_num(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and m.content.isdigit()
        
        try:
            msg = await bot.wait_for('message', timeout=30.0, check=check_num)
            choice = int(msg.content) - 1
            if choice < 0 or choice >= len(matches):
                return await ctx.send("❌ Invalid selection.")
            
            idx, song = matches[choice]
            
            # Confirmation
            await ctx.send(f"Remove **{song['title']}** from `{list_name}`?\nReply with **Y** (yes) or **N** (no)")
            
            def check_confirm(m):
                return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and m.content.lower() in ['y', 'yes', 'n', 'no']
            
            try:
                confirm_msg = await bot.wait_for('message', timeout=30.0, check=check_confirm)
                if is_yes(confirm_msg.content):
                    removed = songs.pop(idx)
                    save_user_lists(ctx.author.id, user_lists)
                    await ctx.send(f"🗑️ Removed **{removed['title']}** from `{list_name}`")
                    log(f"User {ctx.author} removed from list '{list_name}': {removed['title']}", "info")
                else:
                    await ctx.send("❌ Cancelled.")
            except asyncio.TimeoutError:
                await ctx.send("⏰ Timed out.")
            
        except asyncio.TimeoutError:
            await ctx.send("⏰ Timed out.")
    
    @list_group.command(name="play")
    async def list_play(ctx, *, list_name: str):
        """Play all songs from a list."""
        user_lists = get_user_lists(ctx.author.id)
        
        if list_name not in user_lists:
            return await ctx.send(f"❌ List `{list_name}` not found.")
        
        songs = user_lists[list_name]
        if not songs:
            return await ctx.send(f"📭 List `{list_name}` is empty.")
        
        # Check voice connection
        if not ctx.author.voice:
            return await ctx.send("❌ Join a voice channel first!")
        
        vc = ctx.voice_client
        if vc is None:
            vc = await ctx.author.voice.channel.connect()
        elif vc.channel != ctx.author.voice.channel:
            await vc.move_to(ctx.author.voice.channel)
        
        state = get_state(ctx.guild.id)
        
        # Add all songs to queue
        added_count = 0
        for song in songs:
            # Convert stored song to playable format
            song_info = {
                "title": song["title"],
                "webpage_url": song["url"],
                "url": song["url"],
                "duration": song.get("duration", 0),
                "_needs_resolve": True
            }
            state["queue"].append(song_info)
            added_count += 1
        
        await ctx.send(f"▶️ Added **{added_count} songs** from list `{list_name}` to queue!")
        log(f"User {ctx.author} played list '{list_name}' with {added_count} songs", "info")
        
        # Start playing if not already
        if not vc.is_playing() and not vc.is_paused():
            play_next(ctx.guild.id, vc, ctx)
    
    @list_group.command(name="shuffle")
    async def list_shuffle(ctx, *, list_name: str):
        """Shuffle the songs in a list (permanently reorders)."""
        import random
        
        user_lists = get_user_lists(ctx.author.id)
        
        if list_name not in user_lists:
            return await ctx.send(f"❌ List `{list_name}` not found.")
        
        songs = user_lists[list_name]
        if len(songs) < 2:
            return await ctx.send(f"❌ Need at least 2 songs to shuffle.")
        
        random.shuffle(songs)
        save_user_lists(ctx.author.id, user_lists)
        
        await ctx.send(f"🔀 Shuffled list `{list_name}` ({len(songs)} songs)")
        log(f"User {ctx.author} shuffled list '{list_name}'", "info")
    
    @list_group.command(name="rename")
    async def list_rename(ctx, old_name: str, *, new_name: str):
        """Rename a list."""
        if not new_name or len(new_name) > 50:
            return await ctx.send("❌ New name must be 1-50 characters.")
        
        user_lists = get_user_lists(ctx.author.id)
        
        if old_name not in user_lists:
            return await ctx.send(f"❌ List `{old_name}` not found.")
        
        if new_name in user_lists:
            return await ctx.send(f"❌ List `{new_name}` already exists.")
        
        # Confirmation
        await ctx.send(f"Rename `{old_name}` to `{new_name}`?\nReply with **Y** (yes) or **N** (no)")
        
        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and m.content.lower() in ['y', 'yes', 'n', 'no']
        
        try:
            msg = await bot.wait_for('message', timeout=30.0, check=check)
            if is_yes(msg.content):
                user_lists[new_name] = user_lists.pop(old_name)
                save_user_lists(ctx.author.id, user_lists)
                await ctx.send(f"✏️ Renamed `{old_name}` to `{new_name}`")
                log(f"User {ctx.author} renamed list '{old_name}' to '{new_name}'", "info")
            else:
                await ctx.send("❌ Cancelled.")
        except asyncio.TimeoutError:
            await ctx.send("⏰ Timed out.")