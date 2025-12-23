import discord
from discord.ext import commands
from discord.ui import View, Button, Select
import aiosqlite
import asyncio
from config_manager import config_manager

class LadderSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_ladder(self, guild_id, name):
        async with aiosqlite.connect("bot_data.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM ladders WHERE guild_id = ? AND lower(name) = ?", (guild_id, name.lower())) as cursor:
                return await cursor.fetchone()

    async def get_player(self, ladder_id, user_id):
        async with aiosqlite.connect("bot_data.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM ladder_players WHERE ladder_id = ? AND user_id = ?", (ladder_id, user_id)) as cursor:
                return await cursor.fetchone()

    @commands.hybrid_group(name="ladder", description="Competitive Ladder System")
    async def ladder(self, ctx):
        pass

    @ladder.command(name="create", description="Create a new ladder (Admin)")
    @commands.has_permissions(administrator=True)
    async def create(self, ctx, name: str):
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("Admin only.", ephemeral=True)

        try:
            async with aiosqlite.connect("bot_data.db") as db:
                await db.execute("INSERT INTO ladders (guild_id, name) VALUES (?, ?)", (ctx.guild.id, name))
                await db.commit()
            await ctx.send(f"✅ Ladder **{name}** created!", ephemeral=True)
        except Exception:
            await ctx.send(f"Ladder **{name}** likely already exists.", ephemeral=True)

    @ladder.command(name="join", description="Join a ladder")
    async def join(self, ctx, name: str):
        ladder = await self.get_ladder(ctx.guild.id, name)
        if not ladder: return await ctx.send("Ladder not found.", ephemeral=True)

        async with aiosqlite.connect("bot_data.db") as db:
            try:
                await db.execute("INSERT INTO ladder_players (ladder_id, user_id) VALUES (?, ?)", (ladder['id'], ctx.author.id))
                await db.commit()
                await ctx.send(f"✅ Joined **{ladder['name']}**!", ephemeral=True)
            except:
                await ctx.send("You are already in this ladder.", ephemeral=True)

    @ladder.command(name="leaderboard", description="View ladder rankings")
    async def leaderboard(self, ctx, name: str):
        ladder = await self.get_ladder(ctx.guild.id, name)
        if not ladder: return await ctx.send("Ladder not found.", ephemeral=True)

        async with aiosqlite.connect("bot_data.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM ladder_players WHERE ladder_id = ? ORDER BY elo DESC LIMIT 10", (ladder['id'],)) as cursor:
                players = await cursor.fetchall()

        embed = discord.Embed(title=f"🏆 {ladder['name']} Leaderboard", color=discord.Color.gold())
        for i, p in enumerate(players, 1):
            user = ctx.guild.get_member(p['user_id'])
            u_name = user.display_name if user else f"User {p['user_id']}"
            embed.add_field(name=f"#{i} {u_name}", value=f"ELO: {p['elo']} | W: {p['wins']} | L: {p['losses']}", inline=False)

        await ctx.send(embed=embed)

    @ladder.command(name="challenge", description="Challenge a player to a ranked match")
    async def challenge(self, ctx, opponent: discord.Member, ladder_name: str, wager: int = 0):
        if opponent.id == ctx.author.id or opponent.bot:
            return await ctx.send("Invalid opponent.", ephemeral=True)

        ladder = await self.get_ladder(ctx.guild.id, ladder_name)
        if not ladder: return await ctx.send("Ladder not found.", ephemeral=True)

        p1 = await self.get_player(ladder['id'], ctx.author.id)
        p2 = await self.get_player(ladder['id'], opponent.id)

        if not p1: return await ctx.send(f"You are not in {ladder_name}. Use `/ladder join`.", ephemeral=True)
        if not p2: return await ctx.send(f"{opponent.display_name} is not in {ladder_name}.", ephemeral=True)

        # Wager Logic
        if wager > 0:
            econ = self.bot.get_cog("Economy")
            bal = await econ.get_balance(ctx.author.id)
            if bal < wager: return await ctx.send(f"Insufficient funds. You have {bal}.", ephemeral=True)
            # Deduct Escrow
            await econ.update_balance(ctx.author.id, -wager)

        # Create Match
        async with aiosqlite.connect("bot_data.db") as db:
            cursor = await db.execute("""
                INSERT INTO ladder_matches (ladder_id, p1_id, p2_id, wager, status)
                VALUES (?, ?, ?, ?, 'PENDING')
            """, (ladder['id'], ctx.author.id, opponent.id, wager))
            match_id = cursor.lastrowid
            await db.commit()

        embed = discord.Embed(title="⚔️ Ranked Challenge", description=f"{ctx.author.mention} challenges {opponent.mention} in **{ladder_name}**!\nWager: {wager}", color=discord.Color.red())
        view = ChallengeView(match_id, opponent.id, wager, ctx.author.id, self.bot)
        await ctx.send(f"{opponent.mention}", embed=embed, view=view)

    @ladder.command(name="report", description="Report match result")
    async def report(self, ctx):
        # Find active match
        async with aiosqlite.connect("bot_data.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM ladder_matches
                WHERE (p1_id = ? OR p2_id = ?) AND status IN ('ACTIVE', 'REPORTED')
            """, (ctx.author.id, ctx.author.id)) as cursor:
                match = await cursor.fetchone()

        if not match: return await ctx.send("No active ranked match found.", ephemeral=True)

        view = ReportView(match['id'], match['p1_id'], match['p2_id'], self.bot, self)
        await ctx.send(f"Report result for Match #{match['id']}:", view=view, ephemeral=True)

# --- VIEWS ---

class ChallengeView(View):
    def __init__(self, match_id, target_id, wager, challenger_id, bot):
        super().__init__(timeout=300)
        self.match_id = match_id
        self.target_id = target_id
        self.wager = wager
        self.challenger_id = challenger_id
        self.bot = bot

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
    async def accept(self, interaction, button):
        if interaction.user.id != self.target_id: return

        # Check balance if wager
        if self.wager > 0:
            econ = self.bot.get_cog("Economy")
            bal = await econ.get_balance(self.target_id)
            if bal < self.wager:
                return await interaction.response.send_message("Insufficient funds.", ephemeral=True)
            await econ.update_balance(self.target_id, -self.wager)

        async with aiosqlite.connect("bot_data.db") as db:
            await db.execute("UPDATE ladder_matches SET status = 'ACTIVE' WHERE id = ?", (self.match_id,))
            await db.commit()

        await interaction.response.edit_message(content="✅ Challenge Accepted! Match is LIVE. Use `/ladder report` after playing.", embed=None, view=None)
        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red)
    async def decline(self, interaction, button):
        if interaction.user.id != self.target_id: return

        # Refund Challenger
        if self.wager > 0:
            econ = self.bot.get_cog("Economy")
            await econ.update_balance(self.challenger_id, self.wager)

        async with aiosqlite.connect("bot_data.db") as db:
            await db.execute("DELETE FROM ladder_matches WHERE id = ?", (self.match_id,))
            await db.commit()

        await interaction.response.edit_message(content="❌ Challenge Declined.", embed=None, view=None)
        self.stop()

class ReportView(View):
    def __init__(self, match_id, p1_id, p2_id, bot, cog):
        super().__init__(timeout=None)
        self.match_id = match_id
        self.p1_id = p1_id
        self.p2_id = p2_id
        self.bot = bot
        self.cog = cog

    async def handle_report(self, interaction, winner_id):
        reporter_id = interaction.user.id
        # Determine if reporter is P1 or P2
        is_p1 = reporter_id == self.p1_id

        # Logic: Report 1 (Self Win) or 2 (Opponent Win) ??
        # Simpler: Report who won.
        # Store Actual User ID of Winner in report column?
        # Let's say p1_report stores ID of who P1 thinks won.

        col = "p1_report" if is_p1 else "p2_report"

        async with aiosqlite.connect("bot_data.db") as db:
            await db.execute(f"UPDATE ladder_matches SET {col} = ?, status = 'REPORTED' WHERE id = ?", (winner_id, self.match_id))
            await db.commit()

            # Check for Match
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM ladder_matches WHERE id = ?", (self.match_id,)) as cursor:
                m = await cursor.fetchone()

        if m['p1_report'] and m['p2_report']:
            if m['p1_report'] == m['p2_report']:
                # Consensus
                await self.resolve_match(interaction, m, m['p1_report'])
            else:
                # Dispute
                await interaction.response.send_message("❌ **Dispute!** Reports do not match. Admin intervention needed.", ephemeral=False)
                # Could update status to DISPUTED
        else:
            await interaction.response.send_message("Report submitted. Waiting for opponent confirmation...", ephemeral=True)

    async def resolve_match(self, interaction, match, winner_id):
        loser_id = match['p1_id'] if match['p1_id'] != winner_id else match['p2_id']

        # Calculate ELO
        p_win = await self.cog.get_player(match['ladder_id'], winner_id)
        p_lose = await self.cog.get_player(match['ladder_id'], loser_id)

        k = 32
        prob = 1 / (1 + 10 ** ((p_lose['elo'] - p_win['elo']) / 400))
        delta = int(k * (1 - prob))

        new_w_elo = p_win['elo'] + delta
        new_l_elo = p_lose['elo'] - delta

        async with aiosqlite.connect("bot_data.db") as db:
            # Update Winner
            await db.execute("UPDATE ladder_players SET elo = ?, wins = wins + 1 WHERE ladder_id = ? AND user_id = ?", (new_w_elo, match['ladder_id'], winner_id))
            # Update Loser
            await db.execute("UPDATE ladder_players SET elo = ?, losses = losses + 1 WHERE ladder_id = ? AND user_id = ?", (new_l_elo, match['ladder_id'], loser_id))
            # Close Match
            await db.execute("UPDATE ladder_matches SET status = 'CONFIRMED', winner_id = ? WHERE id = ?", (winner_id, match['id']))
            await db.commit()

        # Payout
        if match['wager'] > 0:
            econ = self.bot.get_cog("Economy")
            await econ.update_balance(winner_id, match['wager'] * 2)

        w_user = interaction.guild.get_member(winner_id)
        await interaction.channel.send(f"🏆 **Match Resolved!**\n{w_user.mention} wins! (+{delta} ELO)")

    @discord.ui.button(label="I Won", style=discord.ButtonStyle.success)
    async def i_won(self, interaction, button):
        if interaction.user.id not in [self.p1_id, self.p2_id]: return
        await self.handle_report(interaction, interaction.user.id)

    @discord.ui.button(label="Opponent Won", style=discord.ButtonStyle.secondary)
    async def opp_won(self, interaction, button):
        if interaction.user.id not in [self.p1_id, self.p2_id]: return
        winner = self.p2_id if interaction.user.id == self.p1_id else self.p1_id
        await self.handle_report(interaction, winner)

async def setup(bot):
    await bot.add_cog(LadderSystem(bot))
