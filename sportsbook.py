import discord
from discord.ext import commands, tasks
from discord.ui import View, Select, Button, Modal, TextInput
import logger
import aiosqlite
from sports_api import sports_client, SPORT_MAPPING, REVERSE_MAPPING
from economy import Economy
import datetime
import asyncio

# --- Confirmation View ---
class ConfirmationView(View):
    def __init__(self, modal_instance, wager, payout):
        super().__init__(timeout=60)
        self.modal = modal_instance
        self.wager = wager
        self.payout = payout
        self.value = None

    @discord.ui.button(label="Confirm Bet", style=discord.ButtonStyle.green, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        # We need to ensure the person clicking is the one who opened the modal.
        # But wait, send_modal is an interaction response. The ConfirmationView is sent as a followup to that interaction?
        # Yes.

        # Check Balance again (sanity check)
        economy = interaction.client.get_cog("Economy")
        balance = await economy.get_balance(interaction.user.id)
        if balance < self.wager:
            await interaction.response.send_message(f"Insufficient funds. You have {balance} coins.", ephemeral=True)
            return

        # Deduct Balance
        await economy.update_balance(interaction.user.id, -self.wager)

        # Save to DB
        async with aiosqlite.connect("bot_data.db") as db:
            await db.execute("""
                INSERT INTO active_sports_bets
                (user_id, guild_id, game_id, sport_key, bet_type, bet_selection, bet_line, wager_amount, potential_payout, status, matchup)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
            """, (interaction.user.id, interaction.guild_id, self.modal.game_id, self.modal.sport_key,
                  self.modal.bet_type, self.modal.selection, str(self.modal.line), self.wager, self.payout, self.modal.matchup))
            await db.commit()

        # Update Message
        embed = discord.Embed(title="✅ Bet Placed Successfully!", color=discord.Color.green())
        embed.description = f"**{self.modal.matchup}**\nYou bet **{self.wager}** on **{self.modal.selection}**"

        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        # User requested to "revert back to selection".
        # Deleting the confirmation message reveals the previous BettingView message which is usually above it.
        # Or we can edit this message to say "Cancelled".
        # User explicitly asked to "revert back".
        # If we delete, it vanishes.
        try:
            await interaction.message.delete()
        except:
            await interaction.response.edit_message(content="Bet Cancelled.", embed=None, view=None)
        self.stop()

# --- Wager Modal ---
class WagerModal(Modal):
    def __init__(self, game_id, sport_key, bet_type, selection, line, potential_payout_func, interaction_view, matchup):
        super().__init__(title="Place Your Bet")
        self.game_id = game_id
        self.sport_key = sport_key
        self.bet_type = bet_type
        self.selection = selection
        self.line = line
        self.potential_payout_func = potential_payout_func
        self.interaction_view = interaction_view # To disable buttons or update UI
        self.matchup = matchup

        self.amount = TextInput(
            label="Wager Amount",
            placeholder="Enter amount (e.g. 100)",
            min_length=1,
            max_length=10,
            required=True
        )
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            wager = int(self.amount.value)
            if wager <= 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Please enter a valid positive integer.", ephemeral=True)
            return

        # Check Balance (First Pass)
        economy = interaction.client.get_cog("Economy")
        if not economy:
            await interaction.response.send_message("Economy system is offline.", ephemeral=True)
            return

        balance = await economy.get_balance(interaction.user.id)
        if balance < wager:
            await interaction.response.send_message(f"Insufficient funds. You have {balance} coins.", ephemeral=True)
            return

        # Calculate Payout
        payout = self.potential_payout_func(wager, self.line)

        # Show Confirmation
        sport_display = REVERSE_MAPPING.get(self.sport_key, self.sport_key)

        embed = discord.Embed(title="Confirm Your Bet", color=discord.Color.gold())
        embed.add_field(name="Sport", value=sport_display, inline=True)
        embed.add_field(name="Matchup", value=self.matchup, inline=True)
        embed.add_field(name="Selection", value=f"{self.selection} ({self.line})", inline=False)
        embed.add_field(name="Wager", value=f"{wager} coins", inline=True)
        embed.add_field(name="Potential Win", value=f"{payout} coins", inline=True)

        view = ConfirmationView(self, wager, payout)
        # Store interaction so View can verify user?
        # Actually interaction.user is available in View callback via interaction obj.
        view.interaction_view = self.interaction_view # Propagate if needed

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# --- Betting View (Odds Buttons) ---
class BettingView(View):
    def __init__(self, game, sport_key):
        super().__init__()
        self.game = game
        self.sport_key = sport_key
        self.game_id = game['id']
        self.matchup = f"{game['away_team']} @ {game['home_team']}"

        bookmaker = next((bm for bm in game.get('bookmakers', []) if bm['key'] == 'draftkings'), None)
        if not bookmaker:
            bookmaker = game['bookmakers'][0] if game.get('bookmakers') else None

        if not bookmaker:
            self.add_item(Button(label="No Odds Available", disabled=True))
            return

        # Moneyline
        h2h = next((m for m in bookmaker['markets'] if m['key'] == 'h2h'), None)
        if h2h:
            for outcome in h2h['outcomes']:
                label = f"{outcome['name']} ({outcome['price']})"
                # Selection is just Team Name
                self.add_item(self.create_bet_button("Moneyline", outcome['name'], outcome['price'], label, discord.ButtonStyle.success))

        # Spreads
        spreads = next((m for m in bookmaker['markets'] if m['key'] == 'spreads'), None)
        if spreads:
            for outcome in spreads['outcomes']:
                point = outcome['point']
                sign = "+" if point > 0 else ""
                label = f"{outcome['name']} {sign}{point} ({outcome['price']})"
                # FIX: Selection = "TeamName:Point"
                selection_val = f"{outcome['name']}:{point}"
                self.add_item(self.create_bet_button("Spread", selection_val, outcome['price'], label, discord.ButtonStyle.primary))

        # Totals
        totals = next((m for m in bookmaker['markets'] if m['key'] == 'totals'), None)
        if totals:
            for outcome in totals['outcomes']:
                label = f"{outcome['name']} {outcome['point']} ({outcome['price']})"
                # FIX: Selection = "Over:Point" or "Under:Point"
                selection_val = f"{outcome['name']}:{outcome['point']}"
                self.add_item(self.create_bet_button("Total", selection_val, outcome['price'], label, discord.ButtonStyle.secondary))

    def create_bet_button(self, bet_type, selection, line, label, style):
        button = Button(label=label, style=style)
        async def callback(interaction: discord.Interaction):
            modal = WagerModal(
                game_id=self.game_id,
                sport_key=self.sport_key,
                bet_type=bet_type,
                selection=selection,
                line=line,
                potential_payout_func=self.calculate_payout,
                interaction_view=self,
                matchup=self.matchup
            )
            await interaction.response.send_modal(modal)
        button.callback = callback
        return button

    def calculate_payout(self, amount, line):
        try:
            line = float(line)
            if line > 0:
                profit = amount * (line / 100)
            else:
                profit = amount / (abs(line) / 100)
            return int(amount + profit)
        except:
            return amount

# --- Game Select ---
class GameSelect(Select):
    def __init__(self, games, sport_key):
        self.games = games
        self.sport_key = sport_key
        options = []
        # Limit to 10 games as requested/safe UI limit
        for game in games[:20]: # 25 is discord limit
            home = game['home_team']
            away = game['away_team']
            start = game['commence_time']
            # Simplify time display? relying on ISO string for now or basic label
            label = f"{away} @ {home}"
            desc = start.split('T')[0] # Date only
            options.append(discord.SelectOption(label=label[:100], description=desc, value=game['id']))

        super().__init__(placeholder="Select a Game...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        game_id = self.values[0]
        selected_game = next((g for g in self.games if g['id'] == game_id), None)

        if not selected_game:
            await interaction.response.send_message("Game data not found.", ephemeral=True)
            return

        embed = discord.Embed(title=f"{selected_game['away_team']} @ {selected_game['home_team']}", color=discord.Color.blue())
        embed.add_field(name="Start Time", value=selected_game['commence_time'].replace("T", " ").replace("Z", " UTC"))

        view = BettingView(selected_game, self.sport_key)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class GameSelectView(View):
    def __init__(self, games, sport_key):
        super().__init__()
        self.add_item(GameSelect(games, sport_key))

# --- Sport Select (Re-used) ---
class SportSelect(Select):
    def __init__(self):
        options = []
        for name in SPORT_MAPPING.keys():
            options.append(discord.SelectOption(label=name, value=name))
        super().__init__(placeholder="Select a Sport...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        sport_name = self.values[0]
        sport_key = sports_client.get_sport_key(sport_name)
        view = CategorySelectView(sport_name, sport_key)
        await interaction.response.edit_message(content=f"You selected **{sport_name}**. What games do you want to see?", view=view, embed=None)

class CategorySelectView(View):
    def __init__(self, sport_name, sport_key):
        super().__init__()
        self.sport_name = sport_name
        self.sport_key = sport_key

    async def fetch_and_show(self, interaction, is_live):
        await interaction.response.defer(ephemeral=True)

        try:
            # OPTIMIZATION: Use get_cached_odds first to avoid API call
            # Only force refresh via admin command
            odds_data = sports_client.get_cached_odds(self.sport_key)

            if not odds_data:
                # If cache is empty, we MIGHT try fetch once or tell user to ask admin to refresh?
                # User requested "Snapshot Logic" (Option B).
                # So we do NOT call API here.
                await interaction.followup.send("No odds data available. Please ask an Admin to `/refresh_odds`.", ephemeral=True)
                return

            # Filter Logic
            filtered = []
            now = datetime.datetime.utcnow()

            for game in odds_data:
                start_str = game['commence_time'].replace('Z', '+00:00')
                start_dt = datetime.datetime.fromisoformat(start_str)
                start_dt = start_dt.replace(tzinfo=None)

                if is_live:
                    if start_dt < now and (now - start_dt).total_seconds() < 4 * 3600:
                        filtered.append(game)
                else:
                    if start_dt > now:
                        filtered.append(game)

            if not filtered:
                msg = "No live games found right now." if is_live else "No upcoming games found."
                await interaction.followup.send(msg, ephemeral=True)
                return

            view = GameSelectView(filtered, self.sport_key)
            mode = "Live" if is_live else "Upcoming"
            await interaction.followup.send(f"Found {len(filtered)} {mode} Games:", view=view, ephemeral=True)

        except Exception as e:
            logger.error(f"Error fetching games: {e}")
            await interaction.followup.send("An error occurred fetching games.", ephemeral=True)

    @discord.ui.button(label="Live Games", style=discord.ButtonStyle.danger, emoji="🔴")
    async def live_games(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.fetch_and_show(interaction, is_live=True)

    @discord.ui.button(label="Upcoming Games", style=discord.ButtonStyle.primary, emoji="📅")
    async def upcoming_games(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.fetch_and_show(interaction, is_live=False)

class SportSelectView(View):
    def __init__(self):
        super().__init__()
        self.add_item(SportSelect())

class Sportsbook(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # self.check_results_loop.start() # DISABLED for Economy Mode

    def cog_unload(self):
        # self.check_results_loop.cancel()
        pass

    @discord.app_commands.command(name="sportsbook", description="Open the Sports Betting Menu")
    async def sportsbook(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🏆 Sportsbook",
            description="Select a sport to view odds and place bets.\nData provided by DraftKings.",
            color=discord.Color.gold()
        )
        view = SportSelectView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.app_commands.command(name="mybets", description="View your sports betting history")
    @discord.app_commands.choices(filter=[
        discord.app_commands.Choice(name="Active Bets", value="active"),
        discord.app_commands.Choice(name="Bet History", value="history"),
        discord.app_commands.Choice(name="All Bets", value="all")
    ])
    async def mybets(self, interaction: discord.Interaction, filter: discord.app_commands.Choice[str] = None):
        filter_val = filter.value if filter else "active"

        user_id = interaction.user.id
        query = "SELECT * FROM active_sports_bets WHERE user_id = ?"
        params = [user_id]

        if filter_val == "active":
            query += " AND status = 'PENDING'"
        elif filter_val == "history":
            query += " AND status != 'PENDING'"

        query += " ORDER BY id DESC LIMIT 20" # Limit to last 20 for now

        async with aiosqlite.connect("bot_data.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(params)) as cursor:
                bets = await cursor.fetchall()

        if not bets:
            await interaction.response.send_message(f"No {filter_val} bets found.", ephemeral=True)
            return

        embed = discord.Embed(title=f"📜 Your {filter_val.capitalize()} Bets", color=discord.Color.blue())

        for bet in bets:
            status_emoji = "⏳"
            if bet['status'] == 'WON': status_emoji = "✅"
            elif bet['status'] == 'LOST': status_emoji = "❌"
            elif bet['status'] == 'PUSH': status_emoji = "🤝"

            selection = bet['bet_selection']
            if ':' in selection: selection = selection.split(':')[0]

            # Clean Sport Name
            sport_name = REVERSE_MAPPING.get(bet['sport_key'], bet['sport_key'])

            # Matchup
            matchup = bet['matchup'] if 'matchup' in bet.keys() and bet['matchup'] else "Unknown Matchup"

            field_name = f"{status_emoji} {sport_name} - {bet['bet_type']}"
            field_val = (f"**Matchup:** {matchup}\n"
                         f"**Selection:** {selection} ({bet['bet_line']})\n"
                         f"**Wager:** {bet['wager_amount']} 🪙\n"
                         f"**Payout:** {bet['potential_payout']} 🪙\n"
                         f"**Date:** {bet['timestamp']}")

            embed.add_field(name=field_name, value=field_val, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.app_commands.command(name="allbets", description="View all active bets (Admin Only)")
    @commands.has_permissions(administrator=True)
    async def allbets(self, interaction: discord.Interaction):
        # Admin Check
        # Use discord.py built-in check or simple permission check
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return

        async with aiosqlite.connect("bot_data.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM active_sports_bets WHERE status = 'PENDING' ORDER BY id DESC LIMIT 25") as cursor:
                bets = await cursor.fetchall()

        if not bets:
            await interaction.response.send_message("No active bets found.", ephemeral=True)
            return

        embed = discord.Embed(title="📜 All Active Bets (Admin View)", color=discord.Color.red())

        for bet in bets:
            user = interaction.guild.get_member(bet['user_id'])
            user_name = user.display_name if user else f"User {bet['user_id']}"

            selection = bet['bet_selection']
            if ':' in selection: selection = selection.split(':')[0]

            sport_name = REVERSE_MAPPING.get(bet['sport_key'], bet['sport_key'])

            # Fallback for old bets without matchup
            matchup = bet['matchup'] if 'matchup' in bet.keys() and bet['matchup'] else "Unknown Matchup"

            field_name = f"{user_name} - {sport_name}"
            field_val = (f"**Matchup**: {matchup}\n"
                         f"**{bet['bet_type']}**: {selection} ({bet['bet_line']})\n"
                         f"**Wager**: {bet['wager_amount']} | **Payout**: {bet['potential_payout']}")

            embed.add_field(name=field_name, value=field_val, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- ADMIN: Force Refresh Odds ---
    @discord.app_commands.command(name="refresh_odds", description="Manually fetch latest odds from API (Admin Only)")
    @commands.has_permissions(administrator=True)
    async def refresh_odds(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Admin only.", ephemeral=True)

        await interaction.response.defer()
        try:
            count = await sports_client.force_refresh_odds()
            await interaction.followup.send(f"✅ Odds refreshed for {count} sports categories.")
        except Exception as e:
            await interaction.followup.send(f"❌ Error refreshing odds: {e}")

    # --- ADMIN: Settle Bets Manually ---
    @discord.app_commands.command(name="settle_bets", description="Manually settle pending bets (Admin Only)")
    @commands.has_permissions(administrator=True)
    async def settle_bets(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Admin only.", ephemeral=True)

        await interaction.response.defer()
        await self.run_settlement_logic(interaction)

    async def run_settlement_logic(self, interaction):
        logger.info("Starting manual settlement...")
        try:
            async with aiosqlite.connect("bot_data.db") as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM active_sports_bets WHERE status = 'PENDING'") as cursor:
                    pending_bets = await cursor.fetchall()

                if not pending_bets:
                    await interaction.followup.send("No pending bets to settle.")
                    return

                bets_by_sport = {}
                for bet in pending_bets:
                    key = bet['sport_key']
                    if key not in bets_by_sport: bets_by_sport[key] = []
                    bets_by_sport[key].append(bet)

                settled_count = 0
                for sport_key, bets in bets_by_sport.items():
                    # Fetch scores (API CALL)
                    scores = await sports_client.get_scores(sport_key)
                    if not scores: continue

                    for bet in bets:
                        game_result = next((g for g in scores if g['id'] == bet['game_id'] and g['completed']), None)
                        if not game_result: continue

                        status = 'PENDING'
                        if not game_result.get('scores'): continue

                        home = game_result['home_team']
                        away = game_result['away_team']
                        home_score = next((int(s['score']) for s in game_result['scores'] if s['name'] == home), 0)
                        away_score = next((int(s['score']) for s in game_result['scores'] if s['name'] == away), 0)

                        # Logic Reuse
                        selection = bet['bet_selection']

                        # Moneyline
                        if bet['bet_type'] == 'Moneyline':
                            if selection == home:
                                status = 'WON' if home_score > away_score else 'LOST'
                            elif selection == away:
                                status = 'WON' if away_score > home_score else 'LOST'

                        # Spread/Total
                        elif ':' in selection:
                            sel_name, point_str = selection.split(':')
                            point = float(point_str)

                            if bet['bet_type'] == 'Spread':
                                if sel_name == home:
                                    status = 'WON' if (home_score + point) > away_score else 'LOST'
                                elif sel_name == away:
                                    status = 'WON' if (away_score + point) > home_score else 'LOST'
                            elif bet['bet_type'] == 'Total':
                                total = home_score + away_score
                                if sel_name == "Over":
                                    status = 'WON' if total > point else 'LOST'
                                elif sel_name == "Under":
                                    status = 'WON' if total < point else 'LOST'
                                elif total == point:
                                    status = 'PUSH'

                        if status != 'PENDING':
                            settled_count += 1
                            if status == 'WON':
                                economy = self.bot.get_cog("Economy")
                                if economy: await economy.update_balance(bet['user_id'], bet['potential_payout'])
                                await db.execute("UPDATE active_sports_bets SET status = 'WON' WHERE id = ?", (bet['id'],))
                            elif status == 'LOST':
                                await db.execute("UPDATE active_sports_bets SET status = 'LOST' WHERE id = ?", (bet['id'],))
                            elif status == 'PUSH':
                                economy = self.bot.get_cog("Economy")
                                if economy: await economy.update_balance(bet['user_id'], bet['wager_amount'])
                                await db.execute("UPDATE active_sports_bets SET status = 'PUSH' WHERE id = ?", (bet['id'],))

                    await db.commit()

            await interaction.followup.send(f"✅ Settlement Complete. Processed {settled_count} bets.")

        except Exception as e:
            logger.error(f"Settlement Error: {e}")
            await interaction.followup.send(f"❌ Error during settlement: {e}")

async def setup(bot):
    await bot.add_cog(Sportsbook(bot))
