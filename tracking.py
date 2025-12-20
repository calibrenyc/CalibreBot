import discord
from discord.ext import commands
from database import db_manager
from config_manager import config_manager
import datetime
import asyncio
import aiosqlite
import logger

class Tracking(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_join_times = {} # {member_id: datetime}

    # --- Helper: Log to Channel ---
    async def log_to_channel(self, guild, embed):
        config = await config_manager.get_guild_config(guild.id)
        log_channel_id = config.get('log_channel_id')
        if log_channel_id:
            try:
                channel = guild.get_channel(int(log_channel_id))
                if not channel:
                    channel = await guild.fetch_channel(int(log_channel_id))

                if channel:
                    await channel.send(embed=embed)
                    logger.debug(f"Logged voice event for {guild.name} to {channel.name}")
                else:
                    logger.warning(f"Log channel ID {log_channel_id} configured for {guild.name} but channel not found.")
            except Exception as e:
                logger.error(f"Failed to send log to channel {log_channel_id} in {guild.name}: {e}")
        else:
            logger.debug(f"No log channel configured for {guild.name}")

    # --- Voice Tracking ---
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot: return

        # Joined
        if before.channel is None and after.channel is not None:
            self.voice_join_times[member.id] = datetime.datetime.now()
            embed = discord.Embed(
                description=f"🎤 {member.mention} **joined** voice channel {after.channel.mention}",
                color=discord.Color.green(),
                timestamp=datetime.datetime.now()
            )
            embed.set_author(name=f"{member}", icon_url=member.display_avatar.url)
            await self.log_to_channel(member.guild, embed)
            logger.voice(f"{member} joined voice channel {after.channel.name}")

        # Left
        elif before.channel is not None and after.channel is None:
            if member.id in self.voice_join_times:
                join_time = self.voice_join_times.pop(member.id)
                duration = datetime.datetime.now() - join_time
                minutes = int(duration.total_seconds() // 60)
                hours = round(duration.total_seconds() / 3600, 2)

                # Award XP (Simple: 1 XP per minute)
                await self.award_voice_xp(member, minutes)

                # Check for Disconnect (Kick)
                disconnector = None
                try:
                    # Wait briefly for audit log to populate
                    await asyncio.sleep(1.0)
                    async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.member_disconnect):
                        if entry.target.id == member.id and entry.created_at > discord.utils.utcnow() - datetime.timedelta(seconds=10):
                            disconnector = entry.user
                            break
                except:
                    pass

                if disconnector:
                    embed = discord.Embed(
                        description=f"🛑 {member.mention} was **disconnected** from {before.channel.mention} by {disconnector.mention}",
                        color=discord.Color.orange(),
                        timestamp=datetime.datetime.now()
                    )
                    logger.voice(f"{member} was disconnected from {before.channel.name} by {disconnector}")
                else:
                    embed = discord.Embed(
                        description=f"👋 {member.mention} **left** voice channel {before.channel.mention}",
                        color=discord.Color.red(),
                        timestamp=datetime.datetime.now()
                    )
                    logger.voice(f"{member} left voice channel {before.channel.name}")

                embed.add_field(name="Duration", value=f"{minutes} mins ({hours} hrs)")
                embed.set_author(name=f"{member}", icon_url=member.display_avatar.url)
                await self.log_to_channel(member.guild, embed)

        # Moved
        elif before.channel is not None and after.channel is not None and before.channel != after.channel:
             embed = discord.Embed(
                description=f"➡️ {member.mention} **moved** from {before.channel.mention} to {after.channel.mention}",
                color=discord.Color.blue(),
                timestamp=datetime.datetime.now()
            )
             await self.log_to_channel(member.guild, embed)
             logger.voice(f"{member} moved from {before.channel.name} to {after.channel.name}")

        # Stream / Camera
        if before.self_stream != after.self_stream:
            action = "started streaming" if after.self_stream else "stopped streaming"
            channel = after.channel or before.channel
            channel_mention = channel.mention if channel else "unknown channel"
            channel_name = channel.name if channel else "unknown channel"

            embed = discord.Embed(
                description=f"🎥 {member.mention} **{action}** in {channel_mention}",
                color=discord.Color.purple(),
                timestamp=datetime.datetime.now()
            )
            await self.log_to_channel(member.guild, embed)
            logger.voice(f"{member} {action} in {channel_name}")

        if before.self_video != after.self_video:
            action = "turned on camera" if after.self_video else "turned off camera"
            channel = after.channel or before.channel
            channel_mention = channel.mention if channel else "unknown channel"
            channel_name = channel.name if channel else "unknown channel"

            embed = discord.Embed(
                description=f"📷 {member.mention} **{action}** in {channel_mention}",
                color=discord.Color.purple(),
                timestamp=datetime.datetime.now()
            )
            await self.log_to_channel(member.guild, embed)
            logger.voice(f"{member} {action} in {channel_name}")

    async def award_voice_xp(self, member, minutes):
        if minutes <= 0: return

        # Fetch Rate
        config = await config_manager.get_guild_config(member.guild.id)
        rate = config.get('xp_rate', 1.0)

        base_xp = minutes * 10 # 10 XP per minute
        xp = int(base_xp * rate)

        # Use Leveling Cog to handle XP and Level Ups
        leveling_cog = self.bot.get_cog("Leveling")
        if leveling_cog:
            leveled_up, new_level = await leveling_cog.add_xp(member.guild.id, member.id, xp)
            if leveled_up:
                # Notify in log channel or DM since they are in voice
                embed = discord.Embed(
                    description=f"🎉 {member.mention} reached **Level {new_level}** via voice activity!",
                    color=discord.Color.gold()
                )
                await self.log_to_channel(member.guild, embed)

    # --- Flagged Words Commands ---
    @commands.hybrid_group(name="flag", description="Manage flagged words")
    async def flag_group(self, ctx):
        pass

    @flag_group.command(name="add", description="Add a word to the flagged list")
    @commands.has_permissions(manage_messages=True)
    async def flag_add(self, ctx, word: str):
        async with aiosqlite.connect("bot_data.db") as db:
            try:
                await db.execute("INSERT INTO flagged_words (guild_id, word) VALUES (?, ?)", (ctx.guild.id, word.lower()))
                await db.commit()
                await ctx.send(f"Added `||{word}||` to flagged list.")
            except aiosqlite.IntegrityError:
                await ctx.send("Word is already flagged.")

    @flag_group.command(name="remove", description="Remove a word from the flagged list")
    @commands.has_permissions(manage_messages=True)
    async def flag_remove(self, ctx, word: str):
        async with aiosqlite.connect("bot_data.db") as db:
            await db.execute("DELETE FROM flagged_words WHERE guild_id = ? AND word = ?", (ctx.guild.id, word.lower()))
            await db.commit()
        await ctx.send(f"Removed `||{word}||` from flagged list.")

    @flag_group.command(name="list", description="List all flagged words")
    @commands.has_permissions(manage_messages=True)
    async def flag_list(self, ctx):
        async with aiosqlite.connect("bot_data.db") as db:
            async with db.execute("SELECT word FROM flagged_words WHERE guild_id = ?", (ctx.guild.id,)) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            await ctx.send("No flagged words set.")
            return

        words = [f"||{row[0]}||" for row in rows]
        await ctx.send(f"Flagged Words: {', '.join(words)}")

    # --- Kick Tracking ---
    @commands.Cog.listener()
    async def on_member_remove(self, member):
        # Wait a bit for audit log to populate
        await asyncio.sleep(1)
        async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.kick):
            if entry.target.id == member.id and entry.created_at > discord.utils.utcnow() - datetime.timedelta(seconds=10):
                # It was a kick
                embed = discord.Embed(
                    title="👢 Member Kicked",
                    description=f"{member.mention} was kicked by {entry.user.mention}",
                    color=discord.Color.orange(),
                    timestamp=discord.utils.utcnow()
                )
                embed.add_field(name="Reason", value=entry.reason or "No reason provided")
                await self.log_to_channel(member.guild, embed)
                break

    # --- Flagged Words ---
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return

        async with aiosqlite.connect("bot_data.db") as db:
            async with db.execute("SELECT word FROM flagged_words WHERE guild_id = ?", (message.guild.id,)) as cursor:
                async for row in cursor:
                    word = row[0]
                    if word.lower() in message.content.lower():
                        # Flagged
                        embed = discord.Embed(
                            title="⚠️ Flagged Word Detected",
                            description=f"{message.author.mention} used a flagged word in {message.channel.mention}",
                            color=discord.Color.yellow(),
                            timestamp=discord.utils.utcnow()
                        )
                        embed.add_field(name="Word", value=f"||{word}||") # Spoiler the word
                        embed.add_field(name="Content", value=f"||{message.content}||")
                        await self.log_to_channel(message.guild, embed)
                        # Optional: Auto-delete? User didn't specify. Just log for now.
                        break

    # --- Moderation Commands ---
    @commands.hybrid_command(name="warn", description="Warn a user")
    @commands.has_permissions(kick_members=True)
    async def warn(self, ctx, user: discord.Member, *, reason: str):
        async with aiosqlite.connect("bot_data.db") as db:
            await db.execute("INSERT INTO warnings (guild_id, user_id, moderator_id, reason) VALUES (?, ?, ?, ?)",
                             (ctx.guild.id, user.id, ctx.author.id, reason))
            await db.commit()

            # Count warnings
            async with db.execute("SELECT COUNT(*) FROM warnings WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, user.id)) as cursor:
                count = (await cursor.fetchone())[0]

        embed = discord.Embed(title="User Warned", color=discord.Color.gold())
        embed.add_field(name="User", value=user.mention)
        embed.add_field(name="Reason", value=reason)
        embed.add_field(name="Total Warnings", value=str(count))
        await ctx.send(embed=embed)

        # Log
        await self.log_to_channel(ctx.guild, embed)

        try:
            await user.send(f"You were warned in **{ctx.guild.name}**: {reason}")
        except:
            pass

    @commands.hybrid_command(name="tempmute", description="Timeout a user")
    @commands.has_permissions(moderate_members=True)
    async def tempmute(self, ctx, user: discord.Member, minutes: int, *, reason: str = "No reason"):
        try:
            duration = datetime.timedelta(minutes=minutes)
            await user.timeout(duration, reason=reason)
            embed = discord.Embed(title="User Timed Out", color=discord.Color.dark_grey())
            embed.add_field(name="User", value=user.mention)
            embed.add_field(name="Duration", value=f"{minutes} mins")
            embed.add_field(name="Reason", value=reason)
            await ctx.send(embed=embed)
            await self.log_to_channel(ctx.guild, embed)
        except Exception as e:
            await ctx.send(f"Failed to timeout user: {e}")

    @commands.hybrid_command(name="modlogs", description="Check moderation logs for a user")
    async def modlogs(self, ctx, user: discord.Member):
         async with aiosqlite.connect("bot_data.db") as db:
             db.row_factory = aiosqlite.Row
             async with db.execute("SELECT * FROM warnings WHERE guild_id = ? AND user_id = ? ORDER BY timestamp DESC LIMIT 10", (ctx.guild.id, user.id)) as cursor:
                 rows = await cursor.fetchall()

         if not rows:
             await ctx.send(f"{user.mention} has no warnings.")
             return

         embed = discord.Embed(title=f"Mod Logs: {user.display_name}", color=discord.Color.blue())
         for row in rows:
             embed.add_field(
                 name=f"Warned by <@{row['moderator_id']}> on {row['timestamp']}",
                 value=row['reason'],
                 inline=False
             )
         await ctx.send(embed=embed)
