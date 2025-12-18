import discord
from discord.ext import commands, tasks
import aiosqlite
import datetime

class Birthdays(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_birthdays.start()

    @commands.hybrid_group(name="birthday")
    async def birthday(self, ctx):
        pass

    @birthday.command(name="set")
    async def birthday_set(self, ctx, date: str):
        """Format: DD/MM (e.g. 25/12)"""
        try:
            d = datetime.datetime.strptime(date, "%d/%m")
            day = d.day
            month = d.month

            async with aiosqlite.connect("bot_data.db") as db:
                await db.execute("""
                    INSERT INTO birthdays (user_id, day, month) VALUES (?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET day = ?, month = ?
                """, (ctx.author.id, day, month, day, month))
                await db.commit()

            await ctx.send(f"Birthday set to {date}!")
        except ValueError:
            await ctx.send("Invalid format. Use DD/MM.")

    @tasks.loop(hours=24)
    async def check_birthdays(self):
        now = datetime.datetime.now()
        day, month = now.day, now.month

        async with aiosqlite.connect("bot_data.db") as db:
            async with db.execute("SELECT user_id FROM birthdays WHERE day = ? AND month = ?", (day, month)) as cursor:
                users = await cursor.fetchall()

        if not users: return

        # Announce in all guilds where user is present?
        # Or configured channel? Assuming configured channel 'general' or 'bot-logs' fallback?
        # Ideally, we add 'birthday_channel_id' to config.
        # For now, let's use 'log_channel_id' or general.

        from database import db_manager

        for user_row in users:
            user_id = user_row[0]
            # Find mutual guilds
            for guild in self.bot.guilds:
                member = guild.get_member(user_id)
                if member:
                    # Find channel
                    # Try to find a channel named 'general' or 'chat'
                    channel = discord.utils.get(guild.text_channels, name="general")
                    if not channel:
                        # Fallback to log channel
                        config = await db_manager.get_guild_config(guild.id)
                        lid = config.get('log_channel_id')
                        if lid: channel = guild.get_channel(lid)

                    if channel:
                        await channel.send(f"🎂 Happy Birthday {member.mention}! 🎉")

    @check_birthdays.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()
