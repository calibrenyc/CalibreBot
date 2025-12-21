import discord
from discord.ext import commands
from discord.ui import View, Button
import random
import asyncio

class Casino(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # Helper to check balance
    async def check_balance(self, user_id, amount):
        economy = self.bot.get_cog("Economy")
        if not economy: return False, "Economy offline."
        bal = await economy.get_balance(user_id)
        if bal < amount: return False, f"Insufficient funds. You have {bal} coins."
        return True, bal

    # --- High/Low ---
    @commands.hybrid_command(name="highlow", description="Guess if next card is higher or lower")
    async def highlow(self, ctx, wager: int):
        if wager <= 0: return await ctx.send("Wager must be positive.", ephemeral=True)

        ok, msg = await self.check_balance(ctx.author.id, wager)
        if not ok: return await ctx.send(msg, ephemeral=True)

        # Start game logic
        await self.start_highlow(ctx, wager)

    async def start_highlow(self, ctx, wager):
        # Determine if we need to deduct wager again?
        # If this is a "Play Again", the previous loop ended.
        # So we need to check balance and deduct for every new game.
        # But this function is called by the command (which checks) AND the button (which needs to check).

        # NOTE: The command checks but doesn't deduct?
        # Wait, previous implementation didn't deduct upfront for HighLow.
        # It updated balance at the end (+wager or -wager).
        # We'll stick to that logic, but ensure "Play Again" checks balance.

        # Deck logic
        suits = ['♠️', '♥️', '♦️', '♣️']
        ranks = list(range(2, 11)) + ['J', 'Q', 'K', 'A']
        values = {r: i for i, r in enumerate(ranks, start=2)} # 2=2, ..., A=14

        def draw():
            rank = random.choice(ranks)
            suit = random.choice(suits)
            return rank, suit, values[rank]

        current_rank, current_suit, current_val = draw()

        embed = discord.Embed(title="🃏 High or Low", color=discord.Color.purple())
        embed.description = f"Current Card: **{current_rank}{current_suit}**\nWager: {wager}"

        # View needs to know if it's a new game or restart?
        # Actually, we can just create a new view instance.
        view = HighLowView(ctx, wager, current_val, self.bot)
        if isinstance(ctx, discord.Interaction):
             if not ctx.response.is_done():
                 await ctx.response.send_message(embed=embed, view=view)
             else:
                 await ctx.followup.send(embed=embed, view=view)
        else:
             await ctx.send(embed=embed, view=view)

    # --- Blackjack ---
    @commands.hybrid_command(name="blackjack", description="Play Blackjack against the dealer")
    async def blackjack(self, ctx, wager: int):
        if wager <= 0: return await ctx.send("Wager must be positive.", ephemeral=True)

        ok, msg = await self.check_balance(ctx.author.id, wager)
        if not ok: return await ctx.send(msg, ephemeral=True)

        # Deduct wager immediately for BJ
        economy = self.bot.get_cog("Economy")
        await economy.update_balance(ctx.author.id, -wager)

        game = BlackjackGame(ctx, wager, economy)
        await game.start()

    # --- Buffalo Slots ---
    @commands.hybrid_command(name="slots", description="Play Buffalo Slots")
    async def slots(self, ctx, wager: int):
        if wager <= 0: return await ctx.send("Wager must be positive.", ephemeral=True)

        ok, msg = await self.check_balance(ctx.author.id, wager)
        if not ok: return await ctx.send(msg, ephemeral=True)

        # Deduct wager
        economy = self.bot.get_cog("Economy")
        await economy.update_balance(ctx.author.id, -wager)

        # Symbols
        symbols = ["🍒", "🔔", "🍊", "🐺", "🦅", "🦬"]
        weights = [30, 25, 20, 15, 7, 3]

        # Animation: Spin 3 times
        embed = discord.Embed(title="🎰 Buffalo Slots", color=discord.Color.gold())
        embed.description = "🎰 Spinning..."
        msg = await ctx.send(embed=embed)

        for _ in range(2):
            fake_grid = []
            for _ in range(3):
                row = random.choices(symbols, k=5)
                fake_grid.append(" | ".join(row))
            embed.description = "**" + "\n".join(fake_grid) + "**"
            await msg.edit(embed=embed)
            await asyncio.sleep(0.7)

        # Final Result
        grid = []
        for _ in range(3):
            row = random.choices(symbols, weights=weights, k=5)
            grid.append(row)

        payout_multipliers = {
            "🍒": {3: 2, 4: 5, 5: 10},
            "🔔": {3: 5, 4: 10, 5: 20},
            "🍊": {3: 5, 4: 10, 5: 20},
            "🐺": {3: 10, 4: 25, 5: 50},
            "🦅": {3: 20, 4: 50, 5: 100},
            "🦬": {3: 50, 4: 200, 5: 1000}
        }

        total_payout = 0
        winning_lines = []

        for r_idx, row in enumerate(grid):
            first = row[0]
            count = 1
            for s in row[1:]:
                if s == first: count += 1
                else: break

            if count >= 3:
                mult = payout_multipliers[first][count]
                win = wager * mult
                total_payout += win
                winning_lines.append(f"Row {r_idx+1}: {count}x {first} (+{win})")

        display = "\n".join([" | ".join(row) for row in grid])
        embed.description = f"**{display}**\n\n"

        view = PlayAgainView(ctx, wager, "slots", self.bot) # Add Play Again

        if total_payout > 0:
            embed.description += f"**WINNER!**\n" + "\n".join(winning_lines)
            embed.color = discord.Color.green()
            await economy.update_balance(ctx.author.id, total_payout)
            embed.add_field(name="Result", value=f"Wager: {wager} | Payout: {total_payout}")
        else:
            embed.description += "**No Win**"
            embed.color = discord.Color.red()
            embed.add_field(name="Result", value=f"Wager: {wager} | Lost")

        await msg.edit(embed=embed, view=view)


# --- Reusable Play Again View ---
class PlayAgainView(View):
    def __init__(self, ctx, wager, game_type, bot):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.wager = wager
        self.game_type = game_type
        self.bot = bot

    @discord.ui.button(label="Play Again", style=discord.ButtonStyle.primary, emoji="🔄")
    async def play_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("Not your game.", ephemeral=True)

        # Relaunch command logic
        # We need to manually check balance and deduct again because we are bypassing the command decorator
        casino_cog = self.bot.get_cog("Casino")
        economy = self.bot.get_cog("Economy")

        # Balance Check
        bal = await economy.get_balance(interaction.user.id)
        if bal < self.wager:
            return await interaction.response.send_message("Insufficient funds to play again.", ephemeral=True)

        await interaction.response.defer() # Acknowledge click
        self.stop() # Stop listening to old buttons

        if self.game_type == "slots":
            # Logic duped from command, ideally refactor to shared method
            # For brevity, calling command via bot.invoke is hard with interaction context mismatch
            # So we call the Casino method directly (which I should refactor to be callable)
            # Refactoring slots to `run_slots`
            await casino_cog.slots(self.ctx, self.wager) # Re-using context is safe enough

        elif self.game_type == "blackjack":
            await economy.update_balance(interaction.user.id, -self.wager)
            game = BlackjackGame(self.ctx, self.wager, economy)
            await game.start()

        elif self.game_type == "highlow":
            # HighLow logic doesn't deduct upfront, checks at start
            await casino_cog.start_highlow(self.ctx, self.wager)


# --- High/Low View ---
class HighLowView(View):
    def __init__(self, ctx, wager, current_val, bot):
        super().__init__(timeout=30)
        self.ctx = ctx
        self.wager = wager
        self.current_val = current_val
        self.bot = bot
        self.economy = bot.get_cog("Economy")

    async def interaction_check(self, interaction):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("Not your game.", ephemeral=True)
            return False
        return True

    async def end_game(self, interaction, won, next_card_str):
        if won:
            await self.economy.update_balance(self.ctx.author.id, self.wager)
            result = f"Correct! The card was {next_card_str}.\nYou won {self.wager} coins!"
            color = discord.Color.green()
        else:
            await self.economy.update_balance(self.ctx.author.id, -self.wager)
            result = f"Wrong! The card was {next_card_str}.\nYou lost {self.wager} coins."
            color = discord.Color.red()

        embed = discord.Embed(title="🃏 High or Low Result", description=result, color=color)

        # Add Play Again Button
        view = PlayAgainView(self.ctx, self.wager, "highlow", self.bot)

        await interaction.response.edit_message(embed=embed, view=view)
        self.stop()

    def draw(self):
        suits = ['♠️', '♥️', '♦️', '♣️']
        ranks = list(range(2, 11)) + ['J', 'Q', 'K', 'A']
        values = {r: i for i, r in enumerate(ranks, start=2)}
        r = random.choice(ranks)
        s = random.choice(suits)
        return r, s, values[r]

    @discord.ui.button(label="Higher", style=discord.ButtonStyle.success)
    async def higher(self, interaction: discord.Interaction, button: discord.ui.Button):
        rank, suit, val = self.draw()
        card_str = f"{rank}{suit}"
        if val > self.current_val:
            await self.end_game(interaction, True, card_str)
        elif val < self.current_val:
            await self.end_game(interaction, False, card_str)
        else:
             embed = discord.Embed(title="🃏 Tie!", description=f"Card was {card_str}. Push.", color=discord.Color.gold())
             await interaction.response.edit_message(embed=embed, view=None)
             self.stop()

    @discord.ui.button(label="Lower", style=discord.ButtonStyle.danger)
    async def lower(self, interaction: discord.Interaction, button: discord.ui.Button):
        rank, suit, val = self.draw()
        card_str = f"{rank}{suit}"
        if val < self.current_val:
            await self.end_game(interaction, True, card_str)
        elif val > self.current_val:
            await self.end_game(interaction, False, card_str)
        else:
             embed = discord.Embed(title="🃏 Tie!", description=f"Card was {card_str}. Push.", color=discord.Color.gold())
             await interaction.response.edit_message(embed=embed, view=None)
             self.stop()

# --- Blackjack Logic ---
class BlackjackGame:
    def __init__(self, ctx, wager, economy):
        self.ctx = ctx
        self.wager = wager
        self.economy = economy
        # Deck: Standard 52 card logic representation
        self.suits = ['♠️', '♥️', '♦️', '♣️']
        self.ranks = {
            2: '2️⃣', 3: '3️⃣', 4: '4️⃣', 5: '5️⃣', 6: '6️⃣', 7: '7️⃣', 8: '8️⃣', 9: '9️⃣', 10: '🔟',
            11: 'J', 12: 'Q', 13: 'K', 14: 'A'
        }
        self.values = {k: min(k, 10) for k in range(2, 15)}
        self.values[14] = 11 # Ace default

        self.player_hand = []
        self.dealer_hand = []

    def deal_card(self):
        rank_val = random.randint(2, 14)
        suit = random.choice(self.suits)
        display = f"{self.ranks[rank_val]}{suit}"
        value = self.values[rank_val]
        return {'display': display, 'value': value}

    def calc_score(self, hand):
        score = sum(c['value'] for c in hand)
        aces = sum(1 for c in hand if c['value'] == 11)
        while score > 21 and aces:
            score -= 10
            aces -= 1
        return score

    async def start(self):
        self.player_hand = [self.deal_card(), self.deal_card()]
        self.dealer_hand = [self.deal_card(), self.deal_card()]
        await self.update_view()

    async def update_view(self, ended=False, result_msg=None):
        p_score = self.calc_score(self.player_hand)
        d_score = self.calc_score(self.dealer_hand)

        p_hand_str = " ".join([c['display'] for c in self.player_hand])

        if ended:
            d_hand_str = " ".join([c['display'] for c in self.dealer_hand])
            desc = f"**Your Hand:** {p_hand_str} (Score: {p_score})\n"
            desc += f"**Dealer Hand:** {d_hand_str} (Score: {d_score})\n\n{result_msg}"

            # Show Play Again button
            view = PlayAgainView(self.ctx, self.wager, "blackjack", self.ctx.bot)
        else:
            # Hide hole card
            d_hand_str = f"{self.dealer_hand[0]['display']} 🂠"
            desc = f"**Your Hand:** {p_hand_str} (Score: {p_score})\n"
            desc += f"**Dealer Hand:** {d_hand_str}"
            view = BlackjackView(self)

        embed = discord.Embed(title="♠️ Blackjack", description=desc, color=discord.Color.blue())

        if hasattr(self, 'message'):
            await self.message.edit(embed=embed, view=view)
        else:
            self.message = await self.ctx.send(embed=embed, view=view)

    async def hit(self, interaction):
        self.player_hand.append(self.deal_card())
        if self.calc_score(self.player_hand) > 21:
            await self.update_view(ended=True, result_msg="❌ **Bust!** You lose.")
        else:
            await interaction.response.defer()
            await self.update_view()

    async def stand(self, interaction):
        while self.calc_score(self.dealer_hand) < 17:
            self.dealer_hand.append(self.deal_card())

        p_score = self.calc_score(self.player_hand)
        d_score = self.calc_score(self.dealer_hand)

        if d_score > 21:
            await self.economy.update_balance(self.ctx.author.id, self.wager * 2)
            msg = "✅ **Dealer Bust!** You win!"
        elif p_score > d_score:
            await self.economy.update_balance(self.ctx.author.id, self.wager * 2)
            msg = "✅ **You Win!**"
        elif p_score == d_score:
            await self.economy.update_balance(self.ctx.author.id, self.wager) # Refund
            msg = "🤝 **Push.** Money back."
        else:
            msg = "❌ **Dealer Wins.**"

        await self.update_view(ended=True, result_msg=msg)

    async def double(self, interaction):
        bal = await self.economy.get_balance(self.ctx.author.id)
        if bal < self.wager:
            await interaction.response.send_message("Insufficient funds to double.", ephemeral=True)
            return

        await self.economy.update_balance(self.ctx.author.id, -self.wager)
        self.wager *= 2

        self.player_hand.append(self.deal_card())
        p_score = self.calc_score(self.player_hand)

        if p_score > 21:
             await self.update_view(ended=True, result_msg="❌ **Bust!** You lose (Doubled).")
        else:
             await self.stand(interaction)

class BlackjackView(View):
    def __init__(self, game):
        super().__init__(timeout=60)
        self.game = game

    async def interaction_check(self, interaction):
        if interaction.user != self.game.ctx.author: return False
        return True

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.game.hit(interaction)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.game.stand(interaction)

    @discord.ui.button(label="Double", style=discord.ButtonStyle.success)
    async def double(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.game.double(interaction)

async def setup(bot):
    await bot.add_cog(Casino(bot))
