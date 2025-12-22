import discord
from discord.ext import commands
import aiosqlite
import random
import math
import logger
from discord.ui import Select, View, Button, Modal, TextInput
from config_manager import config_manager

class TCFC(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_fighter(self, user_id):
        async with aiosqlite.connect("bot_data.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM tcfc_fighters WHERE user_id = ?", (user_id,)) as cursor:
                return await cursor.fetchone()

    async def create_fighter(self, user_id):
        async with aiosqlite.connect("bot_data.db") as db:
            await db.execute("INSERT OR IGNORE INTO tcfc_fighters (user_id) VALUES (?)", (user_id,))
            await db.commit()

    def calculate_odds(self, elo_a, elo_b):
        prob_a = 1 / (1 + 10 ** ((elo_b - elo_a) / 400))
        def prob_to_american(p):
            if p == 0.5: return 100 # Even
            if p > 0.5: return int(-100 * (p / (1-p)))
            else: return int(100 * ((1-p)/p))
        return prob_to_american(prob_a), prob_to_american(1-prob_a)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Skip check for setup commands
        if interaction.command.name in ['setup', 'create_tournament', 'create_fight', 'report']:
            return True

        config = await config_manager.get_guild_config(interaction.guild_id)
        channel_id = config.get('tcfc_channel_id')

        if channel_id and interaction.channel_id != channel_id:
            await interaction.response.send_message(f"TCFC commands are locked to <#{channel_id}>.", ephemeral=True)
            return False
        return True

    @commands.hybrid_group(name="tcfc", description="The Collective Fighting League")
    async def tcfc(self, ctx):
        pass

    # --- SETUP COMMAND ---
    @tcfc.command(name="setup", description="Configure TCFC (Channel & Analyst Role) - Owner Only")
    async def setup_tcfc(self, ctx):
        if ctx.author.id != ctx.guild.owner_id:
            return await ctx.send("Only the Server Owner can configure TCFC.", ephemeral=True)

        view = SetupView(ctx)
        await ctx.send("Starting TCFC Setup...", view=view, ephemeral=True)

    @tcfc.command(name="register", description="Register as a fighter")
    async def register(self, ctx):
        existing = await self.get_fighter(ctx.author.id)
        if existing: return await ctx.send("Already registered!", ephemeral=True)
        await self.create_fighter(ctx.author.id)
        await ctx.send(f"✅ Welcome, {ctx.author.mention}! ELO: 1000.")

    @tcfc.command(name="leaderboard", description="Show leaderboard")
    async def leaderboard(self, ctx):
        async with aiosqlite.connect("bot_data.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM tcfc_fighters ORDER BY elo DESC LIMIT 10") as cursor:
                fighters = await cursor.fetchall()

        embed = discord.Embed(title="🥊 TCFC Leaderboard", color=discord.Color.red())
        for idx, f in enumerate(fighters, 1):
            user = ctx.guild.get_member(f['user_id'])
            name = user.display_name if user else f"User {f['user_id']}"
            embed.add_field(name=f"#{idx} {name}", value=f"ELO: {f['elo']} | W/L: {f['wins']}/{f['losses']} | KO: {f['kos']}", inline=False)
        await ctx.send(embed=embed)

    @tcfc.command(name="create_tournament", description="Create fight bracket (Admin)")
    @commands.has_permissions(administrator=True)
    async def create_tournament(self, ctx, name: str, mode: str = "random"):
        async with aiosqlite.connect("bot_data.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM tcfc_fighters") as cursor:
                fighters = await cursor.fetchall()

        if len(fighters) < 2: return await ctx.send("Not enough fighters.")

        fighters = list(fighters)
        if mode == "random": random.shuffle(fighters)
        else: fighters.sort(key=lambda x: x['elo'], reverse=True)

        pairs = []
        for i in range(0, len(fighters) - 1, 2):
            pairs.append((fighters[i], fighters[i+1]))

        desc = ""
        async with aiosqlite.connect("bot_data.db") as db:
            for f1, f2 in pairs:
                user1 = ctx.guild.get_member(f1['user_id'])
                user2 = ctx.guild.get_member(f2['user_id'])
                n1 = user1.display_name if user1 else "Unk"
                n2 = user2.display_name if user2 else "Unk"

                desc += f"🥊 **{n1}** vs **{n2}**\n"

                await db.execute("INSERT INTO tcfc_matches (fighter_a, fighter_b, tournament_id, status) VALUES (?, ?, ?, 'OPEN')",
                                 (f1['user_id'], f2['user_id'], name))
            await db.commit()

        embed = discord.Embed(title=f"🏆 Tournament: {name}", description=desc, color=discord.Color.gold())
        await ctx.send(embed=embed)

    @tcfc.command(name="create_fight", description="Create a single ranked fight (Admin)")
    @commands.has_permissions(administrator=True)
    async def create_fight(self, ctx, fighter_a: discord.Member, fighter_b: discord.Member):
        if fighter_a.id == fighter_b.id:
            return await ctx.send("Fighters must be different.", ephemeral=True)

        f1 = await self.get_fighter(fighter_a.id)
        f2 = await self.get_fighter(fighter_b.id)

        if not f1: return await ctx.send(f"{fighter_a.mention} is not registered.", ephemeral=True)
        if not f2: return await ctx.send(f"{fighter_b.mention} is not registered.", ephemeral=True)

        async with aiosqlite.connect("bot_data.db") as db:
            await db.execute("INSERT INTO tcfc_matches (fighter_a, fighter_b, tournament_id, status) VALUES (?, ?, 'Single Match', 'OPEN')",
                             (fighter_a.id, fighter_b.id))
            await db.commit()

        embed = discord.Embed(title="🥊 New Fight Created", color=discord.Color.green())
        embed.description = f"**{fighter_a.display_name}** vs **{fighter_b.display_name}**\nStatus: OPEN for betting."
        await ctx.send(embed=embed)

    @tcfc.command(name="active_fights", description="Show active fights")
    async def active_fights(self, ctx):
        async with aiosqlite.connect("bot_data.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM tcfc_matches WHERE status = 'OPEN'") as cursor:
                matches = await cursor.fetchall()

        if not matches: return await ctx.send("No active fights.")

        embed = discord.Embed(title="🥊 Active Fights", color=discord.Color.red())
        for m in matches:
            f1 = await self.get_fighter(m['fighter_a'])
            f2 = await self.get_fighter(m['fighter_b'])

            u1 = ctx.guild.get_member(m['fighter_a'])
            u2 = ctx.guild.get_member(m['fighter_b'])
            n1 = u1.display_name if u1 else "Unk"
            n2 = u2.display_name if u2 else "Unk"

            elo1 = f1['elo'] if f1 else 1000
            elo2 = f2['elo'] if f2 else 1000

            odds1, odds2 = self.calculate_odds(elo1, elo2)

            embed.add_field(
                name=f"Match #{m['id']}",
                value=f"{n1} ({odds1}) vs {n2} ({odds2})",
                inline=False
            )
        await ctx.send(embed=embed)

    @tcfc.command(name="report", description="Report fight result (Analyst)")
    async def report(self, ctx, match_id: int, winner: discord.Member, method: str, rounds: int, damage_bonus: float = 0.0):
        # Role Check
        config = await config_manager.get_guild_config(ctx.guild.id)
        analyst_role_id = config.get('tcfc_analyst_role_id')

        is_analyst = False
        if analyst_role_id:
            role = ctx.guild.get_role(analyst_role_id)
            if role and role in ctx.author.roles:
                is_analyst = True

        if not is_analyst and not ctx.author.guild_permissions.administrator:
            return await ctx.send("Only the TCFC Analyst or Admins can report results.", ephemeral=True)

        # 1. Update Match
        async with aiosqlite.connect("bot_data.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM tcfc_matches WHERE id = ? AND status = 'OPEN'", (match_id,)) as cursor:
                match = await cursor.fetchone()

            if not match: return await ctx.send("Match not found or closed.")

            loser_id = match['fighter_a'] if match['fighter_b'] == winner.id else match['fighter_b']

            # 2. Update ELO
            f_win = await self.get_fighter(winner.id)
            f_loss = await self.get_fighter(loser_id)

            elo_w = f_win['elo']
            elo_l = f_loss['elo']

            # ELO Formula
            prob_w = 1 / (1 + 10 ** ((elo_l - elo_w) / 400))
            k_factor = 32

            # Damage Modifier
            change = k_factor * (1 - prob_w) + (damage_bonus * 2) # Arbitrary scaling

            new_w = elo_w + change
            new_l = elo_l - change

            # Save Stats
            await db.execute("UPDATE tcfc_fighters SET elo = ?, wins = wins + 1, kos = kos + ?, rounds_fought = rounds_fought + ? WHERE user_id = ?",
                             (new_w, 1 if method.lower() == 'ko' else 0, rounds, winner.id))

            await db.execute("UPDATE tcfc_fighters SET elo = ?, losses = losses + 1, rounds_fought = rounds_fought + ? WHERE user_id = ?",
                             (new_l, rounds, loser_id))

            await db.execute("UPDATE tcfc_matches SET status = 'RESOLVED', winner_id = ?, method = ?, round = ? WHERE id = ?",
                             (winner.id, method, rounds, match_id))

            # 3. Payout Bets
            async with db.execute("SELECT * FROM tcfc_bets WHERE match_id = ? AND status = 'PENDING'", (match_id,)) as cursor:
                bets = await cursor.fetchall()

            econ = self.bot.get_cog("Economy")
            payout_count = 0

            for bet in bets:
                won = False
                if bet['bet_type'] == 'WINNER' and int(bet['selection']) == winner.id:
                    won = True

                if won:
                    await econ.update_balance(bet['user_id'], bet['wager'] * 2) # Placeholder
                    payout_count += 1
                    await db.execute("UPDATE tcfc_bets SET status = 'WON' WHERE id = ?", (bet['id'],))
                else:
                    await db.execute("UPDATE tcfc_bets SET status = 'LOST' WHERE id = ?", (bet['id'],))

            await db.commit()

        await ctx.send(f"✅ Match Resolved! {winner.display_name} wins! ELO: {int(new_w)} (+{int(change)}). Paid {payout_count} bets.")

    @tcfc.command(name="bet", description="Bet on a TCFC fight")
    async def tcfc_bet(self, ctx):
        # Check permissions handled by interaction_check above

        async with aiosqlite.connect("bot_data.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM tcfc_matches WHERE status = 'OPEN'") as cursor:
                matches = await cursor.fetchall()

        if not matches: return await ctx.send("No matches open for betting.")

        view = MatchSelectView(matches, self.bot, self)
        await ctx.send("Select a match to bet on:", view=view, ephemeral=True)

# --- VIEWS ---

class SetupView(View):
    def __init__(self, ctx):
        super().__init__(timeout=120)
        self.ctx = ctx

    @discord.ui.button(label="Set Channel", style=discord.ButtonStyle.primary, emoji="#️⃣")
    async def set_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Please mention the channel to lock TCFC commands to.", ephemeral=True)

        def check(m): return m.author == self.ctx.author and m.channel == self.ctx.channel and m.channel_mentions

        try:
            msg = await self.ctx.bot.wait_for('message', check=check, timeout=30)
            channel = msg.channel_mentions[0]
            await config_manager.update_guild_config(interaction.guild_id, 'tcfc_channel_id', channel.id)
            await interaction.followup.send(f"✅ TCFC locked to {channel.mention}.", ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("Timed out.", ephemeral=True)

    @discord.ui.button(label="Configure Analyst", style=discord.ButtonStyle.success, emoji="🕵️")
    async def config_analyst(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = AnalystRoleView(self.ctx)
        await interaction.response.send_message("Do you have an existing Analyst role?", view=view, ephemeral=True)

class AnalystRoleView(View):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx

    @discord.ui.button(label="Yes, select existing", style=discord.ButtonStyle.primary)
    async def select_existing(self, interaction: discord.Interaction, button: discord.ui.Button):
        # We can't use RoleSelect in ephemeral nicely without a View update?
        # Actually we can just ask for a mention like channel.
        await interaction.response.send_message("Please mention the existing Analyst role.", ephemeral=True)

        def check(m): return m.author == self.ctx.author and m.channel == self.ctx.channel and m.role_mentions

        try:
            msg = await self.ctx.bot.wait_for('message', check=check, timeout=30)
            role = msg.role_mentions[0]
            await config_manager.update_guild_config(interaction.guild_id, 'tcfc_analyst_role_id', role.id)
            await interaction.followup.send(f"✅ Analyst role set to {role.mention}.", ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("Timed out.", ephemeral=True)

    @discord.ui.button(label="No, create new", style=discord.ButtonStyle.secondary)
    async def create_new(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CreateRoleModal(interaction.guild_id))

class CreateRoleModal(Modal):
    def __init__(self, guild_id):
        super().__init__(title="Create Analyst Role")
        self.guild_id = guild_id
        self.role_name = TextInput(label="Role Name", default="TCFC Analyst")
        self.add_item(self.role_name)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            role = await interaction.guild.create_role(name=self.role_name.value, reason="TCFC Setup")
            await config_manager.update_guild_config(self.guild_id, 'tcfc_analyst_role_id', role.id)
            await interaction.response.send_message(f"✅ Created and set role: {role.mention}", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Failed: {e}", ephemeral=True)

# ... [Previous Betting Views (MatchSelect, etc.) maintained below] ...

class MatchSelect(Select):
    def __init__(self, matches, bot, cog):
        self.matches = matches
        self.bot = bot
        self.cog = cog
        options = []
        for m in matches:
            options.append(discord.SelectOption(label=f"Match #{m['id']}", value=str(m['id'])))
        super().__init__(placeholder="Select Match...", options=options)

    async def callback(self, interaction: discord.Interaction):
        match_id = int(self.values[0])
        # Proceed to Bet Type
        view = BetTypeView(match_id, self.bot, self.cog)
        await interaction.response.edit_message(content="What do you want to bet on?", view=view)

class MatchSelectView(View):
    def __init__(self, matches, bot, cog):
        super().__init__()
        self.add_item(MatchSelect(matches, bot, cog))

class BetTypeView(View):
    def __init__(self, match_id, bot, cog):
        super().__init__()
        self.match_id = match_id
        self.bot = bot
        self.cog = cog

    @discord.ui.button(label="Winner", style=discord.ButtonStyle.primary)
    async def winner(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with aiosqlite.connect("bot_data.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM tcfc_matches WHERE id = ?", (self.match_id,)) as cursor:
                match = await cursor.fetchone()

        view = FighterSelectView(match, self.bot, self.cog)
        await interaction.response.edit_message(content="Who will win?", view=view)

class FighterSelectView(View):
    def __init__(self, match, bot, cog):
        super().__init__()
        self.match = match
        self.bot = bot
        self.cog = cog

        self.add_item(self.create_btn(match['fighter_a'], "Fighter A"))
        self.add_item(self.create_btn(match['fighter_b'], "Fighter B"))

    def create_btn(self, fighter_id, label):
        btn = Button(label=f"Fighter {fighter_id}", style=discord.ButtonStyle.secondary)
        async def cb(interaction):
            await interaction.response.send_modal(WagerModalTCFC(self.match['id'], fighter_id, self.bot))
        btn.callback = cb
        return btn

class WagerModalTCFC(Modal):
    def __init__(self, match_id, selection, bot):
        super().__init__(title="Place Bet")
        self.match_id = match_id
        self.selection = selection
        self.bot = bot
        self.amount = TextInput(label="Amount")
        self.add_item(self.amount)

    async def on_submit(self, interaction):
        try:
            amt = int(self.amount.value)
        except:
            return await interaction.response.send_message("Invalid amount.", ephemeral=True)

        econ = self.bot.get_cog("Economy")
        await econ.update_balance(interaction.user.id, -amt)

        async with aiosqlite.connect("bot_data.db") as db:
            await db.execute("INSERT INTO tcfc_bets (user_id, match_id, bet_type, selection, wager, status) VALUES (?, ?, 'WINNER', ?, ?, 'PENDING')",
                             (interaction.user.id, self.match_id, self.selection, amt))
            await db.commit()

        await interaction.response.send_message(f"Bet {amt} on Fighter {self.selection}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(TCFC(bot))
