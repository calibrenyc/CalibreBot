import discord
from discord.ext import commands
from discord.ui import View, Button, Select
import random
import asyncio
import time
from config_manager import config_manager
import aiosqlite

# --- Deck Helper ---
def get_deck():
    suits = ['♠️', '♥️', '♦️', '♣️']
    ranks = {
        2: '2️⃣', 3: '3️⃣', 4: '4️⃣', 5: '5️⃣', 6: '6️⃣', 7: '7️⃣', 8: '8️⃣', 9: '9️⃣', 10: '🔟',
        11: '🇯', 12: '🇶', 13: '🇰', 14: '🅰️'
    }
    deck = []
    for s in suits:
        for r_val, r_disp in ranks.items():
            val = min(r_val, 10)
            if r_val == 14: val = 11
            deck.append({'display': f"{r_disp}{s}", 'value': val, 'rank': r_val})
    return deck * 4

def evaluate_hand(cards):
    # Sort by rank
    ranks = sorted([c['rank'] for c in cards], reverse=True)
    suits = [c['display'][-1] for c in cards] # Get emoji suit

    # Check Flush
    is_flush = False
    flush_suit = None
    for s in ['♠️', '♥️', '♦️', '♣️']:
        if suits.count(s) >= 5:
            is_flush = True
            flush_suit = s
            break

    # Check Straight
    unique_ranks = sorted(list(set(ranks)), reverse=True)
    is_straight = False
    straight_high = 0

    # Handle Ace low (A, 5, 4, 3, 2)
    if {14, 5, 4, 3, 2}.issubset(set(unique_ranks)):
        is_straight = True
        straight_high = 5

    for i in range(len(unique_ranks) - 4):
        window = unique_ranks[i:i+5]
        if window[0] - window[4] == 4:
            is_straight = True
            straight_high = window[0]
            break

    # Counts
    counts = {r: ranks.count(r) for r in ranks}
    quads = [r for r, c in counts.items() if c == 4]
    trips = [r for r, c in counts.items() if c == 3]
    pairs = [r for r, c in counts.items() if c == 2]

    # 1. Straight Flush
    # This simplified check assumes if you have a straight and a flush, it's a straight flush.
    # A true check would require filtering cards by flush suit first.
    if is_flush and is_straight:
        # Strict check
        flush_cards = [c for c in cards if c['display'][-1] == flush_suit]
        f_ranks = sorted([c['rank'] for c in flush_cards], reverse=True)
        # Check straight again on flush cards
        sf_high = 0
        f_unique = sorted(list(set(f_ranks)), reverse=True)
        if {14, 5, 4, 3, 2}.issubset(set(f_unique)): sf_high = 5
        for i in range(len(f_unique) - 4):
            if f_unique[i] - f_unique[i+4] == 4:
                sf_high = f_unique[i]
                break

        if sf_high > 0: return 800 + sf_high, "Straight Flush"

    # 2. Four of a Kind
    if quads: return 700 + quads[0], "Four of a Kind"

    # 3. Full House
    if trips and pairs: return 600 + trips[0], "Full House"
    if len(trips) >= 2: return 600 + trips[0], "Full House" # Two trips > Full House

    # 4. Flush
    if is_flush: return 500 + ranks[0], "Flush"

    # 5. Straight
    if is_straight: return 400 + straight_high, "Straight"

    # 6. Three of a Kind
    if trips: return 300 + trips[0], "Three of a Kind"

    # 7. Two Pair
    if len(pairs) >= 2: return 200 + pairs[0], "Two Pair"

    # 8. Pair
    if pairs: return 100 + pairs[0], "Pair"

    # 9. High Card
    return ranks[0], "High Card"

class Casino(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.rtp_modifier = 1.0
        self.bot.loop.create_task(self.load_rtp())

    async def load_rtp(self):
        async with aiosqlite.connect("bot_data.db") as db:
            async with db.execute("SELECT value FROM global_config WHERE key = 'rtp_modifier'") as cursor:
                row = await cursor.fetchone()
                if row:
                    self.rtp_modifier = float(row[0])

    async def check_balance(self, user_id, amount):
        economy = self.bot.get_cog("Economy")
        if not economy: return False, "Economy offline."
        bal = await economy.get_balance(user_id)
        if bal < amount: return False, f"Insufficient funds. You have {bal} coins."
        return True, bal

    # --- ADMIN: Set RTP ---
    @discord.app_commands.command(name="set_rtp", description="Set Global Slots RTP Modifier (Admin Only)")
    @commands.has_permissions(administrator=True)
    async def set_rtp(self, interaction: discord.Interaction, value: float):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Admin only.", ephemeral=True)

        self.rtp_modifier = value
        async with aiosqlite.connect("bot_data.db") as db:
            await db.execute("""
                INSERT INTO global_config (key, value) VALUES ('rtp_modifier', ?)
                ON CONFLICT(key) DO UPDATE SET value = ?
            """, (str(value), str(value)))
            await db.commit()
        await interaction.response.send_message(f"🎰 Global Slots RTP Modifier set to {value}", ephemeral=True)

    # --- SLOTS (Buffalo Style - Enhanced) ---
    @commands.hybrid_command(name="slots", description="Play Buffalo Slots (Stake Style)")
    async def slots(self, ctx, wager: int):
        if wager <= 0: return await ctx.send("Wager must be positive.", ephemeral=True)
        ok, msg = await self.check_balance(ctx.author.id, wager)
        if not ok: return await ctx.send(msg, ephemeral=True)

        # Luck Check (Pre-deduction for decision)
        has_luck = False
        async with aiosqlite.connect("bot_data.db") as db:
            async with db.execute("SELECT 1 FROM inventory WHERE user_id = ? AND item_name = 'Lucky Charm'", (ctx.author.id,)) as cursor:
                if await cursor.fetchone(): has_luck = True

        if has_luck:
            # Ask user if they want to use luck
            # Note: LuckChoiceView is defined below, ensure it's available or move it up.
            # In Python, classes defined below are not available above unless inside a method
            # that is called after definition.
            # Since 'slots' is called via command dispatch, 'LuckChoiceView' will be defined by then.
            # However, nested class scope is tricky if not module level.
            # LuckChoiceView is module level (see end of file), so this works fine.
            view = LuckChoiceView(ctx, wager, self)
            msg = await ctx.send("🍀 **Lucky Charm Found!** Do you want to use it for this spin?", view=view)
            # The view handles the rest
        else:
            # Proceed normally
            await self.run_slots(ctx, wager, use_luck=False)

    async def run_slots(self, ctx, wager, use_luck=False):
        econ = self.bot.get_cog("Economy")
        # Deduct Wager (if not already done - Wait, logic separation means we deduct here)
        # We need to re-check balance if we are coming from a button click?
        # Assuming PlayAgainView calls callback -> slots -> check -> logic.
        # But wait, PlayAgainView calls callback.
        # If we use LuckChoiceView, we need to handle the deduction inside run_slots.
        # So we remove deduction from the `slots` command top-level if we branch.
        # Actually `check_balance` returns `True/False` but doesn't deduct.
        # So it's safe to deduct here.

        # Re-check balance just in case
        bal = await econ.get_balance(ctx.author.id)
        if bal < wager:
            return await ctx.send(f"Insufficient funds. You have {bal} coins.")

        await econ.update_balance(ctx.author.id, -wager)

        if use_luck:
            # Consume 1 Lucky Charm
            item_consumed = False
            async with aiosqlite.connect("bot_data.db") as db:
                # Find an entry and remove one
                async with db.execute("SELECT id FROM inventory WHERE user_id = ? AND item_name = 'Lucky Charm' LIMIT 1", (ctx.author.id,)) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        await db.execute("DELETE FROM inventory WHERE id = ?", (row[0],))
                        await db.commit()
                        item_consumed = True

            if not item_consumed:
                use_luck = False
                await ctx.send("⚠️ **Lucky Charm not found!** Spinning normally...", delete_after=5)

        # Symbols (Buffalo Theme)
        # 🐃 = Buffalo (High), 🦅 = Eagle, 🐺 = Wolf, 🦁 = Cougar, 🦌 = Moose
        # 🅰️, 🇰, 🇶, 🇯, 🔟, 9️⃣ = Low
        # 🪙 = Scatter
        # 🃏 = Wild

        symbols = ["9️⃣", "🔟", "🇯", "🇶", "🇰", "🅰️", "🦌", "🦁", "🐺", "🦅", "🐃", "🪙", "🃏"]

        # Weights (Adjusted for RTP)
        # Base: Low symbols high weight, High symbols low weight.
        # RTP Modifier > 1.0 increases chance of High Symbols (Buffalo, Scatter, Wild)
        base_weights = [15, 15, 12, 12, 10, 10, 8, 7, 6, 5, 3, 2, 2]

        if self.rtp_modifier != 1.0:
            # Scale high paying symbols (indices 9-12)
            for i in range(9, 13):
                base_weights[i] = int(base_weights[i] * self.rtp_modifier)

        if use_luck:
            base_weights[10] += 2 # Buffalo
            base_weights[11] += 1 # Scatter
            base_weights[12] += 1 # Wild

        # 5 Reels x 4 Rows (Stake Style Layout)
        rows, cols = 4, 5

        # --- ANIMATION ---
        embed = discord.Embed(title="🎰 Buffalo Legends", color=discord.Color.gold())
        embed.description = "🎰 **SPINNING...**"
        embed.add_field(name="Wager", value=f"{wager} 🪙")
        if use_luck:
            embed.set_footer(text="🍀 LUCK ADDED! Better odds active!")

        if getattr(ctx, 'message_to_edit', None):
             msg = getattr(ctx, 'message_to_edit')
             await msg.edit(embed=embed, view=None) # Clear view
        else:
             msg = await ctx.send(embed=embed)

        # Generate Final Grid First
        final_grid = []
        for _ in range(rows):
            row = random.choices(symbols, weights=base_weights, k=cols)
            final_grid.append(row)

        # Animate: Show columns stopping 1 by 1
        for i in range(cols + 1):
            display_lines = []
            for r in range(rows):
                line = []
                for c in range(cols):
                    if c < i:
                        line.append(final_grid[r][c])
                    else:
                        line.append("🔄") # Spinning
                display_lines.append(" ".join(line))
            display_lines.append(f"**Potential Win: {wager * 10}+**") # Interactive element
            embed.description = "\n".join(display_lines)
            await msg.edit(embed=embed)
            await asyncio.sleep(0.5)

        # --- EVALUATION ---
        total_payout = 0
        winning_lines = []

        # Payouts (Simplified Stake "Ways" logic - Adjacent symbols L->R)
        # We check symbol counts on first 3, 4, 5 reels.
        # Wild (🃏) substitutes.

        pay_table = {
            "9️⃣": 0.2, "🔟": 0.2, "🇯": 0.3, "🇶": 0.3, "🇰": 0.4, "🅰️": 0.4,
            "🦌": 0.5, "🦁": 0.8, "🐺": 1.0, "🦅": 2.0, "🐃": 5.0
        }

        # Check Scatters (Anywhere)
        flat_grid = [s for r in final_grid for s in r]
        scatters = flat_grid.count("🪙")
        free_spins = 0
        if scatters >= 3:
            free_spins = 8 + ((scatters - 3) * 2) # 8, 10, 12...
            winning_lines.append(f"🔥 **{scatters} Scatters! {free_spins} FREE SPINS!**")
            # Bonus Cash Value
            bonus_val = int(wager * free_spins * 0.5)
            total_payout += bonus_val

        # Identify candidate symbols to check for wins (Reel 1 symbols + Wild logic)
        candidates = set()
        for r in range(rows):
            s = final_grid[r][0]
            if s == "🃏":
                candidates.update(symbols) # Wild on Reel 1 starts chains for ANY symbol
            else:
                candidates.add(s)

        for sym in candidates:
            if sym == "🪙" or sym == "🃏": continue # Scatters handled, Wilds handled as sub
            # Count consecutive reels with this symbol (or Wild)
            length = 1
            for c in range(1, cols):
                col_has = False
                for r in range(rows):
                    s = final_grid[r][c]
                    if s == sym or s == "🃏":
                        col_has = True
                        break
                if col_has: length += 1
                else: break

            if length >= 3:
                mult = pay_table.get(sym, 0)
                # Multiplier scales with length: 3x=1, 4x=2, 5x=5
                scale = {3: 1, 4: 2.5, 5: 10}
                win = int(wager * mult * scale[length])
                total_payout += win
                winning_lines.append(f"{length}x {sym} (+{win})")

        # Update Balance
        if total_payout > 0:
            await econ.update_balance(ctx.author.id, total_payout)
            embed.color = discord.Color.green()
            embed.title = "🎰 BIG WIN!" if total_payout > wager * 10 else "🎰 WINNER"
            ft = f"**Total Win: {total_payout} 🪙**"
            if winning_lines: ft += "\n" + "\n".join(winning_lines)
            embed.add_field(name="Result", value=ft, inline=False)
        else:
            embed.color = discord.Color.dark_gray()
            embed.title = "🎰 No Win"
            embed.add_field(name="Result", value="Better luck next time!", inline=False)

        view = PlayAgainView(ctx, wager, "slots", self.bot)
        await msg.edit(embed=embed, view=view)

class LuckChoiceView(View):
    def __init__(self, ctx, wager, cog):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.wager = wager
        self.cog = cog

    @discord.ui.button(label="Spin with Luck (Consume 1 Charm)", style=discord.ButtonStyle.success, emoji="🍀")
    async def use_luck(self, interaction, button):
        if interaction.user != self.ctx.author: return
        self.stop()
        # Pass the message so we can edit it
        self.ctx.message_to_edit = interaction.message
        await interaction.response.defer()
        await self.cog.run_slots(self.ctx, self.wager, use_luck=True)

    @discord.ui.button(label="Spin Normal", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def normal(self, interaction, button):
        if interaction.user != self.ctx.author: return
        self.stop()
        self.ctx.message_to_edit = interaction.message
        await interaction.response.defer()
        await self.cog.run_slots(self.ctx, self.wager, use_luck=False)

    # --- BLACKJACK ---
    @commands.hybrid_command(name="blackjack", description="Play Blackjack")
    async def blackjack(self, ctx, wager: int):
        if wager <= 0: return await ctx.send("Positive wager only.", ephemeral=True)
        ok, msg = await self.check_balance(ctx.author.id, wager)
        if not ok: return await ctx.send(msg, ephemeral=True)

        econ = self.bot.get_cog("Economy")
        await econ.update_balance(ctx.author.id, -wager)

        game = BlackjackGame(ctx, wager, econ)
        await game.start()

    # --- HIGH / LOW ---
    @commands.hybrid_command(name="highlow", description="Guess High or Low")
    async def highlow(self, ctx, wager: int):
        if wager <= 0: return await ctx.send("Positive wager only.", ephemeral=True)
        ok, msg = await self.check_balance(ctx.author.id, wager)
        if not ok: return await ctx.send(msg, ephemeral=True)

        econ = self.bot.get_cog("Economy")
        await econ.update_balance(ctx.author.id, -wager)

        game = HighLowGame(ctx, wager, econ)
        await game.start()

    # --- RIDE THE LINE (Crash) ---
    @commands.hybrid_command(name="crash", description="Ride the line! Cash out before it crashes.")
    async def crash(self, ctx, wager: int):
        if wager <= 0: return await ctx.send("Positive wager only.", ephemeral=True)
        ok, msg = await self.check_balance(ctx.author.id, wager)
        if not ok: return await ctx.send(msg, ephemeral=True)

        econ = self.bot.get_cog("Economy")
        await econ.update_balance(ctx.author.id, -wager)

        embed = discord.Embed(title="🚀 Ride the Line", color=discord.Color.blue())
        embed.description = "Multiplier: **1.00x**\nPossible Win: **" + str(wager) + "**"

        view = CrashView(ctx, wager, econ)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg

        multiplier = 1.00
        crashed = False

        while not view.cashed_out and not crashed:
            await asyncio.sleep(2.0)
            chance = 0.05 + (multiplier * 0.02)
            if random.random() < chance:
                crashed = True
                break

            multiplier += random.uniform(0.1, 0.4)
            view.current_multiplier = multiplier

            embed.description = f"Multiplier: **{multiplier:.2f}x**\nPossible Win: **{int(wager * multiplier)}**"
            embed.color = discord.Color.green()
            try: await msg.edit(embed=embed, view=view)
            except: break

        if crashed and not view.cashed_out:
            view.stop()
            embed.title = "💥 CRASHED!"
            embed.description = f"Crashed at **{multiplier:.2f}x**.\nYou lost {wager}."
            embed.color = discord.Color.red()
            await msg.edit(embed=embed, view=None)

    # --- CASINO POKER (Hold'em) ---
    @commands.hybrid_command(name="poker", description="Casino Hold'em vs Dealer")
    async def poker(self, ctx, wager: int):
        if wager <= 0: return await ctx.send("Positive wager only.", ephemeral=True)
        ok, msg = await self.check_balance(ctx.author.id, wager)
        if not ok: return await ctx.send(msg, ephemeral=True)

        econ = self.bot.get_cog("Economy")
        await econ.update_balance(ctx.author.id, -wager)

        game = CasinoHoldemGame(ctx, wager, econ)
        await game.start()

    # --- PVP POKER (Shootout) ---
    @commands.hybrid_command(name="pvppoker", description="Create a PvP Poker Lobby")
    async def pvppoker(self, ctx, wager: int):
        embed = discord.Embed(title="♠️ PvP Poker Shootout", description=f"Entry Fee: **{wager}**\nClick Join to enter.", color=discord.Color.blurple())
        view = PvPPokerLobby(ctx, wager, self.bot)
        await ctx.send(embed=embed, view=view)

    # --- HORSE RACING (Simple) ---
    @commands.hybrid_command(name="horserace", description="Bet on a horse race")
    async def horserace(self, ctx, wager: int):
        if wager <= 0: return await ctx.send("Positive wager only.", ephemeral=True)
        ok, msg = await self.check_balance(ctx.author.id, wager)
        if not ok: return await ctx.send(msg, ephemeral=True)

        econ = self.bot.get_cog("Economy")
        # We don't deduct yet, we let them choose a horse first.
        # Actually, let's start the lobby/view

        view = HorseRaceView(ctx, wager, econ)
        embed = discord.Embed(title="🐎 Horse Racing", description=f"Wager: **{wager}**\nPick your horse to start!", color=discord.Color.green())
        await ctx.send(embed=embed, view=view)

# --- HELPER CLASSES ---

class CustomContext:
    def __init__(self, bot, interaction):
        self.bot = bot
        self.interaction = interaction
        self.author = interaction.user
        self.guild = interaction.guild
        self.channel = interaction.channel
        self.me = interaction.guild.me if interaction.guild else bot.user

    async def send(self, content=None, **kwargs):
        # Ephemeral handling
        ephemeral = kwargs.pop('ephemeral', False)

        if not self.interaction.response.is_done():
            await self.interaction.response.send_message(content, **kwargs, ephemeral=ephemeral)
            if not ephemeral:
                return await self.interaction.original_response()
            return None
        else:
            return await self.interaction.followup.send(content, **kwargs, ephemeral=ephemeral, wait=True)

    async def defer(self, ephemeral=False):
        await self.interaction.response.defer(ephemeral=ephemeral)

class PlayAgainView(View):
    def __init__(self, ctx, wager, game_type, bot):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.wager = wager
        self.game_type = game_type
        self.bot = bot

    @discord.ui.button(label="Play Again", style=discord.ButtonStyle.primary, emoji="🔄")
    async def play_again(self, interaction, button):
        if interaction.user != self.ctx.author: return
        self.stop()

        # Use CustomContext to ensure interaction handling is correct for repeated plays
        ctx = CustomContext(self.bot, interaction)
        cog = self.bot.get_cog("Casino")

        # Invoke callback with custom context
        if self.game_type == "slots": await cog.slots.callback(cog, ctx, self.wager)
        elif self.game_type == "blackjack": await cog.blackjack.callback(cog, ctx, self.wager)
        elif self.game_type == "highlow": await cog.highlow.callback(cog, ctx, self.wager)

class BlackjackGame:
    def __init__(self, ctx, wager, economy):
        self.ctx = ctx
        self.wager = wager
        self.economy = economy
        self.deck = get_deck()
        random.shuffle(self.deck)
        self.player_hand = []
        self.dealer_hand = []

    def calc(self, hand):
        s = sum(c['value'] for c in hand)
        aces = sum(1 for c in hand if c['rank'] == 14)
        while s > 21 and aces:
            s -= 10
            aces -= 1
        return s

    async def start(self):
        self.player_hand = [self.deck.pop(), self.deck.pop()]
        self.dealer_hand = [self.deck.pop(), self.deck.pop()]
        await self.update_view()

    async def update_view(self, ended=False, msg=""):
        p_s = self.calc(self.player_hand)
        d_s = self.calc(self.dealer_hand)

        p_disp = " ".join([c['display'] for c in self.player_hand])

        embed = discord.Embed(title="♠️ Blackjack", color=discord.Color.dark_blue())
        embed.add_field(name=f"Your Hand ({p_s})", value=p_disp, inline=False)

        if ended:
            d_disp = " ".join([c['display'] for c in self.dealer_hand])
            embed.add_field(name=f"Dealer Hand ({d_s})", value=d_disp, inline=False)
            embed.description = msg
            view = PlayAgainView(self.ctx, self.wager, "blackjack", self.ctx.bot)
        else:
            embed.add_field(name="Dealer Hand", value=f"{self.dealer_hand[0]['display']} 🂠", inline=False)
            view = BlackjackView(self)

        if hasattr(self, 'message'): await self.message.edit(embed=embed, view=view)
        else: self.message = await self.ctx.send(embed=embed, view=view)

    async def hit(self):
        self.player_hand.append(self.deck.pop())
        if self.calc(self.player_hand) > 21:
            await self.update_view(True, "❌ **BUST!**")
        else:
            await self.update_view()

    async def stand(self):
        while self.calc(self.dealer_hand) < 17:
            self.dealer_hand.append(self.deck.pop())
        p = self.calc(self.player_hand)
        d = self.calc(self.dealer_hand)
        if d > 21:
            await self.economy.update_balance(self.ctx.author.id, self.wager * 2)
            await self.update_view(True, "✅ **Dealer Bust! You Win!**")
        elif p > d:
            await self.economy.update_balance(self.ctx.author.id, self.wager * 2)
            await self.update_view(True, "✅ **You Win!**")
        elif p == d:
            await self.economy.update_balance(self.ctx.author.id, self.wager)
            await self.update_view(True, "🤝 **Push.**")
        else:
            await self.update_view(True, "❌ **Dealer Wins.**")

class BlackjackView(View):
    def __init__(self, game):
        super().__init__()
        self.game = game
    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary)
    async def hit(self, interaction, button):
        await interaction.response.defer()
        await self.game.hit()
    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary)
    async def stand(self, interaction, button):
        await interaction.response.defer()
        await self.game.stand()
    @discord.ui.button(label="Double", style=discord.ButtonStyle.success)
    async def double(self, interaction, button):
        # Double Down Logic
        bal = await self.game.economy.get_balance(self.game.ctx.author.id)
        if bal < self.game.wager:
             return await interaction.response.send_message("Insufficient funds to double down.", ephemeral=True)

        await interaction.response.defer()
        # Deduct extra wager
        await self.game.economy.update_balance(self.game.ctx.author.id, -self.game.wager)
        self.game.wager *= 2

        # Hit once then force stand
        self.game.player_hand.append(self.game.deck.pop())

        # Check bust immediately
        if self.game.calc(self.game.player_hand) > 21:
             await self.game.update_view(True, "❌ **BUST!**")
        else:
             # Force Stand
             await self.game.stand()

class CrashView(View):
    def __init__(self, ctx, wager, economy):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.wager = wager
        self.economy = economy
        self.cashed_out = False
        self.current_multiplier = 1.0
        self.message = None

    @discord.ui.button(label="CASH OUT", style=discord.ButtonStyle.success)
    async def cashout(self, interaction, button):
        if interaction.user != self.ctx.author: return
        self.cashed_out = True
        win = int(self.wager * self.current_multiplier)
        await self.economy.update_balance(self.ctx.author.id, win)
        embed = discord.Embed(title="💰 CASHED OUT!", color=discord.Color.green())
        embed.description = f"Cashed at **{self.current_multiplier:.2f}x**\nWon: **{win}**"
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

class HorseRaceView(View):
    def __init__(self, ctx, wager, economy):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.wager = wager
        self.economy = economy

    async def start_race(self, interaction, choice):
        # Deduct
        bal = await self.economy.get_balance(self.ctx.author.id)
        if bal < self.wager: return await interaction.response.send_message("Insufficient funds.", ephemeral=True)
        await self.economy.update_balance(self.ctx.author.id, -self.wager)

        await interaction.response.defer()

        # Setup Race
        horses = [1, 2, 3, 4]
        positions = {h: 0 for h in horses}
        track_length = 20

        embed = discord.Embed(title="🐎 Race in Progress!", color=discord.Color.gold())
        msg = await interaction.followup.send(embed=embed)

        winner = None
        while not winner:
            await asyncio.sleep(1.0)

            # Move horses
            display = ""
            for h in horses:
                move = random.randint(1, 3)
                positions[h] += move

                # Visual
                track = "-" * positions[h] + "🐎" + "-" * (track_length - positions[h])
                if positions[h] >= track_length:
                    positions[h] = track_length
                    track = "-" * track_length + "🏁🐎"
                    if not winner: winner = h

                display += f"**Horse {h}**: {track}\n"

            embed.description = display
            await msg.edit(embed=embed)

        # Result
        if winner == choice:
            payout = self.wager * 3 # 4 horses = 3x payout roughly?
            await self.economy.update_balance(self.ctx.author.id, payout)
            res = f"🎉 **Horse {winner} Won!** You won {payout} coins!"
            col = discord.Color.green()
        else:
            res = f"❌ **Horse {winner} Won.** You picked Horse {choice}."
            col = discord.Color.red()

        embed.title = "🏁 Race Finished!"
        embed.add_field(name="Result", value=res)
        embed.color = col
        await msg.edit(embed=embed)
        self.stop()

    @discord.ui.button(label="Horse 1", style=discord.ButtonStyle.primary)
    async def h1(self, interaction, button): await self.start_race(interaction, 1)
    @discord.ui.button(label="Horse 2", style=discord.ButtonStyle.primary)
    async def h2(self, interaction, button): await self.start_race(interaction, 2)
    @discord.ui.button(label="Horse 3", style=discord.ButtonStyle.primary)
    async def h3(self, interaction, button): await self.start_race(interaction, 3)
    @discord.ui.button(label="Horse 4", style=discord.ButtonStyle.primary)
    async def h4(self, interaction, button): await self.start_race(interaction, 4)

class CasinoHoldemGame:
    def __init__(self, ctx, wager, economy):
        self.ctx = ctx
        self.wager = wager
        self.economy = economy
        self.deck = get_deck()
        random.shuffle(self.deck)
        self.player_cards = [self.deck.pop(), self.deck.pop()]
        self.dealer_cards = [self.deck.pop(), self.deck.pop()]
        self.flop = [self.deck.pop(), self.deck.pop(), self.deck.pop()]

    async def start(self):
        embed = discord.Embed(title="♣️ Casino Hold'em", color=discord.Color.dark_teal())
        embed.add_field(name="Your Hand", value=" ".join([c['display'] for c in self.player_cards]))
        embed.add_field(name="Flop", value=" ".join([c['display'] for c in self.flop]))
        embed.description = f"**Ante:** {self.wager}\n**Call Cost:** {self.wager * 2}\n\nCall to see Turn/River and showdown."
        view = PokerDecisionView(self)
        self.message = await self.ctx.send(embed=embed, view=view)

    async def fold(self, interaction):
        embed = discord.Embed(title="♣️ Folded", description="You forfeited your Ante.", color=discord.Color.red())
        await interaction.response.edit_message(embed=embed, view=None)

    async def call(self, interaction):
        call_amt = self.wager * 2
        bal = await self.economy.get_balance(self.ctx.author.id)
        if bal < call_amt: return await interaction.response.send_message("Insufficient funds.", ephemeral=True)
        await self.economy.update_balance(self.ctx.author.id, -call_amt)

        turn = self.deck.pop()
        river = self.deck.pop()
        board = self.flop + [turn, river]

        p_score, p_desc = evaluate_hand(self.player_cards + board)
        d_score, d_desc = evaluate_hand(self.dealer_cards + board)

        embed = discord.Embed(title="♣️ Showdown", color=discord.Color.gold())
        embed.add_field(name="Board", value=" ".join([c['display'] for c in board]), inline=False)
        embed.add_field(name="Your Hand", value=f"{' '.join([c['display'] for c in self.player_cards])}\n*{p_desc}*", inline=True)
        embed.add_field(name="Dealer Hand", value=f"{' '.join([c['display'] for c in self.dealer_cards])}\n*{d_desc}*", inline=True)

        if p_score > d_score:
            profit = (self.wager + call_amt) * 2
            await self.economy.update_balance(self.ctx.author.id, profit)
            embed.description = f"**YOU WIN!** (+{profit})"
            embed.color = discord.Color.green()
        elif p_score < d_score:
            embed.description = "**DEALER WINS.**"
            embed.color = discord.Color.red()
        else:
            await self.economy.update_balance(self.ctx.author.id, self.wager + call_amt)
            embed.description = "**PUSH.**"

        await interaction.response.edit_message(embed=embed, view=None)

class PokerDecisionView(View):
    def __init__(self, game):
        super().__init__()
        self.game = game
    @discord.ui.button(label="Call", style=discord.ButtonStyle.green)
    async def call(self, interaction, button): await self.game.call(interaction)
    @discord.ui.button(label="Fold", style=discord.ButtonStyle.red)
    async def fold(self, interaction, button): await self.game.fold(interaction)

class PvPPokerLobby(View):
    def __init__(self, ctx, wager, bot):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.wager = wager
        self.bot = bot
        self.players = [ctx.author]
        self.started = False

    @discord.ui.button(label="Join", style=discord.ButtonStyle.success)
    async def join(self, interaction, button):
        if interaction.user in self.players: return await interaction.response.send_message("Joined already.", ephemeral=True)
        self.players.append(interaction.user)
        await interaction.response.send_message(f"Joined! Total: {len(self.players)}", ephemeral=True)

    @discord.ui.button(label="Start", style=discord.ButtonStyle.primary)
    async def start(self, interaction, button):
        if interaction.user != self.ctx.author: return
        if len(self.players) < 2: return await interaction.response.send_message("Need 2+ players.", ephemeral=True)
        self.stop()
        await interaction.response.defer()
        await self.run_game(interaction.channel)

    async def run_game(self, channel):
        deck = get_deck()
        random.shuffle(deck)
        econ = self.bot.get_cog("Economy")
        pot = 0
        hands = {}
        for p in self.players:
            await econ.update_balance(p.id, -self.wager)
            pot += self.wager
            hands[p] = [deck.pop(), deck.pop()]

        board = [deck.pop() for _ in range(5)]
        board_disp = " ".join([c['display'] for c in board])
        await channel.send(f"🃏 **PvP Poker**\nPot: {pot}\nBoard: {board_disp}\nEvaluating...")
        await asyncio.sleep(2)

        best_score = -1
        winners = []
        res = ""
        for p, hand in hands.items():
            s, d = evaluate_hand(hand + board)
            res += f"{p.display_name}: {' '.join([c['display'] for c in hand])} ({d})\n"
            if s > best_score:
                best_score = s
                winners = [p]
            elif s == best_score:
                winners.append(p)

        share = int(pot / len(winners))
        for w in winners: await econ.update_balance(w.id, share)

        embed = discord.Embed(title="🏆 Poker Results", description=res, color=discord.Color.gold())
        embed.add_field(name="Winners", value=", ".join([w.mention for w in winners]) + f" (+{share})")
        await channel.send(embed=embed)

class HighLowGame:
    def __init__(self, ctx, wager, economy):
        self.ctx = ctx
        self.wager = wager
        self.economy = economy
        self.deck = get_deck()
        random.shuffle(self.deck)
        self.current_card = self.deck.pop()

    async def start(self):
        embed = discord.Embed(title="🃏 High or Low", color=discord.Color.purple())
        embed.description = f"Current Card: **{self.current_card['display']}**\nWager: {self.wager}"
        view = HighLowInteract(self)
        self.message = await self.ctx.send(embed=embed, view=view)

    async def guess(self, interaction, choice):
        next_card = self.deck.pop()
        won = False
        if choice == "higher" and next_card['value'] > self.current_card['value']: won = True
        elif choice == "lower" and next_card['value'] < self.current_card['value']: won = True

        if won:
            await self.economy.update_balance(self.ctx.author.id, self.wager * 2)
            res = "✅ **Correct!**"
            col = discord.Color.green()
        else:
            res = "❌ **Wrong!**"
            col = discord.Color.red()

        embed = discord.Embed(title="🃏 Result", description=f"{res}\nNext Card: {next_card['display']}", color=col)
        view = PlayAgainView(self.ctx, self.wager, "highlow", self.ctx.bot)
        await interaction.response.edit_message(embed=embed, view=view)

class HighLowInteract(View):
    def __init__(self, game):
        super().__init__()
        self.game = game
    @discord.ui.button(label="Higher", style=discord.ButtonStyle.success)
    async def higher(self, interaction, button): await self.game.guess(interaction, "higher")
    @discord.ui.button(label="Lower", style=discord.ButtonStyle.danger)
    async def lower(self, interaction, button): await self.game.guess(interaction, "lower")

async def setup(bot):
    await bot.add_cog(Casino(bot))
