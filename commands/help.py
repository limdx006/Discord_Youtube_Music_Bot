import discord
from discord.ext import commands


def setup_help(bot, prefix, command_descriptions):
    """
    Sets up the custom help command.
    """

    # Remove the default help command
    bot.remove_command("help")

    @bot.command(name="help", aliases=["h", "commands"])
    async def help_command(ctx, command_name: str = None):
        """
        Shows help information for all commands or a specific command.
        """

        # If user asks for help on a specific command
        if command_name:
            cmd_name = command_name.lower()
            command = bot.get_command(cmd_name)
            if not command:
                return await ctx.send(f"❌ Command `!{command_name}` not found.")

            # Use command.name (actual command name) to look up description
            description = command_descriptions.get(
                command.name, "No description available."
            )

            # Build specific command help embed
            embed = discord.Embed(
                title=f"📖 Help: !{command.name}",
                description=description,
                color=0x5865F2,
            )

            # Add aliases if any
            if command.aliases:
                embed.add_field(
                    name="Aliases",
                    value=", ".join([f"`!{a}`" for a in command.aliases]),
                    inline=False,
                )

            # Add usage based on signature
            signature = command.signature
            usage = (
                f"`!{command.name} {signature}`" if signature else f"`!{command.name}`"
            )
            embed.add_field(name="Usage", value=usage, inline=False)

            # Add examples based on command
            examples = {
                "play": f"`!play never gonna give you up`\n`!play https://youtube.com/watch?v=...`",
                "volume": "`!volume 50` (sets volume to 50%)",
                "lyrics": "`!lyrics` (current song)\n`!lyrics bohemian rhapsody`",
                "autoplay": "`!autoplay` (toggle on/off)",
            }
            if command.name in examples:
                embed.add_field(
                    name="Examples", value=examples[command.name], inline=False
                )

            return await ctx.send(embed=embed)

        # Main help menu - all commands
        embed = discord.Embed(
            title="🎵 Music Bot Commands",
            description=f"Prefix: `{prefix}` | Use `{prefix}help <command>` for details",
            color=0x5865F2,
        )

        # Music playback commands
        playback_cmds = [
            f"`{prefix}play` - {command_descriptions['play']}",
            f"`{prefix}skip` - {command_descriptions['skip']}",
            f"`{prefix}pause` - {command_descriptions['pause']}",
            f"`{prefix}resume` - {command_descriptions['resume']}",
            f"`{prefix}stop` - {command_descriptions['stop']}",
            f"`{prefix}volume` - {command_descriptions['volume']}",
        ]
        embed.add_field(
            name="🎶 Playback", value="\n".join(playback_cmds), inline=False
        )

        # Queue management commands
        queue_cmds = [
            f"`{prefix}queue` - {command_descriptions['queue']}",
            f"`{prefix}shuffle` - {command_descriptions['shuffle']}",
        ]
        embed.add_field(name="📋 Queue", value="\n".join(queue_cmds), inline=False)

        # Utility commands
        utility_cmds = [
            f"`{prefix}lyrics` - {command_descriptions['lyrics']}",
            f"`{prefix}autoplay` - {command_descriptions['autoplay']}",
            f"`{prefix}leave` - {command_descriptions['leave']}",
            f"`{prefix}help` - {command_descriptions['help']}",
        ]
        embed.add_field(name="🛠️ Utility", value="\n".join(utility_cmds), inline=False)

        # Quick tips
        embed.set_footer(
            text="💡 Tip: You can use playlist URLs with !play • Supports YouTube/YouTube Music"
        )

        await ctx.send(embed=embed)
