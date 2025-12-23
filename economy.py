import discord
from discord.ext import commands
import aiosqlite
import random
import datetime

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_balance(self, user_id):
        async with aiosqlite.connect("bot_data.db") as db:
            async with db.execute("SELECT balance FROM global_users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def update_balance(self, user_id, amount):
        async with aiosqlite.connect("bot_data.db") as db:
            # Upsert
            await db.execute("""
                INSERT INTO global_users (user_id, balance) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?
            """, (user_id, amount, amount))
            await db.commit()

            # Fetch new balance
            async with db.execute("SELECT balance FROM global_users WHERE user_id = ?", (user_id,)) as cursor:
                return (await cursor.fetchone())[0]

    @commands.hybrid_command(name="daily", description="Collect your daily coins")
    async def daily(self, ctx):
        user_id = ctx.author.id
        now = datetime.datetime.now().timestamp()

        async with aiosqlite.connect("bot_data.db") as db:
            async with db.execute("SELECT last_daily FROM global_users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                last_daily = row[0] if row else 0

        if now - last_daily < 86400: # 24 hours
            hours_left = int((86400 - (now - last_daily)) / 3600)
            await ctx.send(f"You must wait {hours_left} more hours.", ephemeral=True)
            return

        amount = 100 # Daily amount
        new_bal = await self.update_balance(user_id, amount)

        async with aiosqlite.connect("bot_data.db") as db:
            await db.execute("UPDATE global_users SET last_daily = ? WHERE user_id = ?", (now, user_id))
            await db.commit()

        await ctx.send(f"💰 You claimed {amount} coins! Balance: {new_bal}")

    @commands.hybrid_command(name="balance", description="Check your balance")
    async def balance(self, ctx, user: discord.Member = None):
        user = user or ctx.author
        bal = await self.get_balance(user.id)
        embed = discord.Embed(title=f"{user.display_name}'s Balance", description=f"💰 {bal} coins", color=discord.Color.green())
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="moneyleaderboard", description="Show top 5 richest members")
    async def money_leaderboard(self, ctx):
        # 1. Get all member IDs in this guild
        member_ids = [m.id for m in ctx.guild.members if not m.bot]
        if not member_ids:
            return await ctx.send("No members found.", ephemeral=True)

        # 2. Chunking (batch size 500)
        chunks = [member_ids[i:i + 500] for i in range(0, len(member_ids), 500)]
        all_rows = []

        async with aiosqlite.connect("bot_data.db") as db:
            for chunk in chunks:
                placeholders = ",".join("?" for _ in chunk)
                query = f"SELECT user_id, balance FROM global_users WHERE user_id IN ({placeholders}) AND balance > 0"
                async with db.execute(query, tuple(chunk)) as cursor:
                    rows = await cursor.fetchall()
                    all_rows.extend(rows)

        # 3. Sort and limit
        # all_rows is list of (user_id, balance) tuples
        all_rows.sort(key=lambda x: x[1], reverse=True)
        top_5 = all_rows[:5]

        if not top_5:
            return await ctx.send("No one has any money yet!", ephemeral=True)

        embed = discord.Embed(title=f"💰 {ctx.guild.name} Richest Members", color=discord.Color.gold())

        for idx, (uid, bal) in enumerate(top_5, start=1):
            member = ctx.guild.get_member(uid)
            name = member.display_name if member else f"User {uid}"
            embed.add_field(name=f"#{idx} {name}", value=f"{bal} coins", inline=False)

        await ctx.send(embed=embed)

    @commands.hybrid_group(name="gamble", description="Gambling games")
    async def gamble(self, ctx):
        pass

    @gamble.command(name="rps", description="Play Rock-Paper-Scissors for coins")
    async def rps(self, ctx, amount: int, choice: str):
        bal = await self.get_balance(ctx.author.id)
        if bal < amount: return await ctx.send("Insufficient funds.")
        if amount < 1: return await ctx.send("Amount must be positive.")

        choices = ['rock', 'paper', 'scissors']
        choice = choice.lower()
        if choice not in choices: return await ctx.send("Choose rock, paper, or scissors.")

        bot_choice = random.choice(choices)
        result = "lost"

        if choice == bot_choice:
            result = "tie"
        elif (choice == 'rock' and bot_choice == 'scissors') or \
             (choice == 'paper' and bot_choice == 'rock') or \
             (choice == 'scissors' and bot_choice == 'paper'):
            result = "won"

        if result == "won":
            new_bal = await self.update_balance(ctx.author.id, amount)
            msg = f"Bot chose {bot_choice}. You won {amount} coins! Balance: {new_bal}"
        elif result == "lost":
            new_bal = await self.update_balance(ctx.author.id, -amount)
            msg = f"Bot chose {bot_choice}. You lost {amount} coins. Balance: {new_bal}"
        else:
            msg = f"Bot chose {bot_choice}. It's a tie!"

        await ctx.send(msg)

    # --- Shop ---
    @commands.hybrid_group(name="shop", description="Server shop system")
    async def shop(self, ctx):
        pass

    @shop.command(name="list", description="List available items in the shop")
    async def shop_list(self, ctx):
        async with aiosqlite.connect("bot_data.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM shop_items WHERE guild_id = ?", (ctx.guild.id,)) as cursor:
                items = await cursor.fetchall()

        if not items: return await ctx.send("Shop is empty.")

        embed = discord.Embed(title="Server Shop", color=discord.Color.gold())
        for item in items:
            itype = item['item_type'] if item['item_type'] else "ROLE"

            reward_text = ""
            if itype == "ROLE":
                role = ctx.guild.get_role(item['role_id'])
                role_name = role.name if role else "Deleted Role"
                reward_text = f"Role: {role_name}"
            elif itype == "LUCK":
                reward_text = "Effect: Increases Casino Luck"
            elif itype == "UNLOCK":
                reward_text = "Effect: Unlocks Special Commands"
            else:
                reward_text = f"Type: {itype}"

            embed.add_field(name=f"{item['name']} - {item['price']} coins", value=f"{reward_text}\n{item['description']}", inline=False)
        await ctx.send(embed=embed)

    @shop.command(name="buy", description="Buy an item from the shop")
    async def shop_buy(self, ctx, item_name: str):
        async with aiosqlite.connect("bot_data.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM shop_items WHERE guild_id = ? AND lower(name) = ?", (ctx.guild.id, item_name.lower())) as cursor:
                item = await cursor.fetchone()

        if not item: return await ctx.send("Item not found.")

        bal = await self.get_balance(ctx.author.id)
        if bal < item['price']: return await ctx.send("Insufficient funds.")

        role_id = item['role_id']
        role = ctx.guild.get_role(role_id) if role_id else None

        # Logic for Inventory Items (No Role)
        # If role_id is 0 or None, it's a pure inventory item (e.g. Lucky Charm)
        is_inventory_item = (role_id == 0 or role_id is None)

        if not is_inventory_item and not role:
             return await ctx.send("Role associated with this item no longer exists.")

        await self.update_balance(ctx.author.id, -item['price'])

        try:
            if role:
                await ctx.author.add_roles(role, reason="Bought from shop")

            # Add to Inventory DB
            async with aiosqlite.connect("bot_data.db") as db:
                await db.execute("INSERT INTO inventory (user_id, guild_id, item_name) VALUES (?, ?, ?)",
                                 (ctx.author.id, ctx.guild.id, item['name']))
                await db.commit()

            msg = f"You bought **{item['name']}**!"
            if role: msg += f" Received role {role.name}."
            await ctx.send(msg)

        except Exception as e:
            await self.update_balance(ctx.author.id, item['price']) # Refund
            await ctx.send(f"Transaction failed: {e}. Refunded.")

    @commands.hybrid_command(name="inventory", description="Check your inventory items")
    async def inventory(self, ctx):
        async with aiosqlite.connect("bot_data.db") as db:
            async with db.execute("SELECT item_name, count(*) FROM inventory WHERE user_id = ? GROUP BY item_name", (ctx.author.id,)) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            return await ctx.send("Your inventory is empty.", ephemeral=True)

        embed = discord.Embed(title=f"{ctx.author.display_name}'s Inventory", color=discord.Color.blue())
        desc = ""
        for name, count in rows:
            desc += f"**{name}**: x{count}\n"
        embed.description = desc
        await ctx.send(embed=embed)

    @shop.command(name="add", description="Add an item to the shop (Admin)")
    @discord.app_commands.describe(
        item_type="Type of item (ROLE, LUCK, UNLOCK)",
        role="Role to reward (Required if type is ROLE)"
    )
    @discord.app_commands.choices(item_type=[
        discord.app_commands.Choice(name="Role Reward", value="ROLE"),
        discord.app_commands.Choice(name="Luck Boost", value="LUCK"),
        discord.app_commands.Choice(name="Command Unlock", value="UNLOCK")
    ])
    @commands.has_permissions(administrator=True)
    async def shop_add(self, ctx, name: str, price: int, item_type: discord.app_commands.Choice[str], role: discord.Role = None, description: str = "No description"):
        type_val = item_type.value

        if type_val == "ROLE" and not role:
            return await ctx.send("You must provide a role for ROLE type items.", ephemeral=True)

        role_id = role.id if role else 0

        async with aiosqlite.connect("bot_data.db") as db:
            await db.execute("INSERT INTO shop_items (guild_id, name, price, role_id, description, item_type) VALUES (?, ?, ?, ?, ?, ?)",
                             (ctx.guild.id, name, price, role_id, description, type_val))
            await db.commit()
        await ctx.send(f"Added {name} ({type_val}) to shop.")

    @shop.command(name="remove", description="Remove an item from the shop (Admin)")
    @commands.has_permissions(administrator=True)
    async def shop_remove(self, ctx, item_name: str):
        async with aiosqlite.connect("bot_data.db") as db:
            async with db.execute("SELECT 1 FROM shop_items WHERE guild_id = ? AND lower(name) = ?", (ctx.guild.id, item_name.lower())) as cursor:
                if not await cursor.fetchone():
                    return await ctx.send("Item not found.", ephemeral=True)

            await db.execute("DELETE FROM shop_items WHERE guild_id = ? AND lower(name) = ?", (ctx.guild.id, item_name.lower()))
            await db.commit()
        await ctx.send(f"Removed **{item_name}** from the shop.")

    # --- Custom Bets ---
    @commands.hybrid_group(name="bet", description="Betting system")
    async def bet(self, ctx):
        pass

    @bet.command(name="create", description="Create a new bet (Admin)")
    @commands.has_permissions(administrator=True)
    async def bet_create(self, ctx, description: str, options: str):
        # Options separate by comma
        opt_list = [o.strip() for o in options.split(',')]
        import json
        async with aiosqlite.connect("bot_data.db") as db:
            cursor = await db.execute("INSERT INTO active_bets (guild_id, description, options, creator_id) VALUES (?, ?, ?, ?)",
                             (ctx.guild.id, description, json.dumps(opt_list), ctx.author.id))
            await db.commit()
            bet_id = cursor.lastrowid

        await ctx.send(f"Bet created! ID: {bet_id}\nOptions: {', '.join(opt_list)}")

    @bet.command(name="place", description="Place a bet on an active event")
    async def bet_place(self, ctx, bet_id: int, option: str, amount: int):
        bal = await self.get_balance(ctx.author.id)
        if bal < amount: return await ctx.send("Insufficient funds.")
        if amount < 1: return await ctx.send("Positive amounts only.")

        async with aiosqlite.connect("bot_data.db") as db:
            # Check bet
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM active_bets WHERE id = ? AND status = 'OPEN'", (bet_id,)) as cursor:
                bet = await cursor.fetchone()

            if not bet: return await ctx.send("Bet invalid or closed.")

            # Check option
            import json
            opts = json.loads(bet['options'])
            if option not in opts: return await ctx.send(f"Invalid option. Choices: {', '.join(opts)}")

            # Deduct
            await self.update_balance(ctx.author.id, -amount)

            # Record
            await db.execute("INSERT INTO bet_entries (bet_id, user_id, option, amount) VALUES (?, ?, ?, ?)",
                             (bet_id, ctx.author.id, option, amount))
            await db.commit()

        await ctx.send(f"Placed {amount} on {option} for Bet #{bet_id}.")

    @bet.command(name="resolve", description="Resolve a bet and distribute winnings (Admin)")
    @commands.has_permissions(administrator=True)
    async def bet_resolve(self, ctx, bet_id: int, winning_option: str):
        async with aiosqlite.connect("bot_data.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM active_bets WHERE id = ?", (bet_id,)) as cursor:
                bet = await cursor.fetchone()

            if not bet or bet['status'] != 'OPEN': return await ctx.send("Invalid bet.")

            # Get winners
            async with db.execute("SELECT * FROM bet_entries WHERE bet_id = ?", (bet_id,)) as cursor:
                entries = await cursor.fetchall()

            total_pool = sum(e['amount'] for e in entries)
            winners = [e for e in entries if e['option'] == winning_option]
            winning_pool = sum(e['amount'] for e in winners)

            if winning_pool == 0:
                # House wins? Or refund? Let's refund everyone if no one won?
                # Or house keeps. Let's say house keeps.
                await ctx.send(f"No one bet on {winning_option}. Pot lost.")
            else:
                # Distribute
                for w in winners:
                    share = w['amount'] / winning_pool
                    payout = int(total_pool * share)
                    await self.update_balance(w['user_id'], payout)

            await db.execute("UPDATE active_bets SET status = 'RESOLVED', winning_option = ? WHERE id = ?", (winning_option, bet_id))
            await db.commit()

        await ctx.send(f"Bet #{bet_id} resolved! Winner: {winning_option}. Pool: {total_pool}.")

    # --- Admin Money Commands (v2.2.2) ---
    @commands.hybrid_command(name="add_money", description="Give coins to a user (Admin Only)")
    @commands.has_permissions(administrator=True)
    async def add_money(self, ctx, user: discord.Member, amount: int):
        if amount <= 0:
            return await ctx.send("Amount must be positive.", ephemeral=True)

        new_bal = await self.update_balance(user.id, amount)
        await ctx.send(f"✅ Added {amount} coins to {user.mention}. New Balance: {new_bal}")

    @commands.hybrid_command(name="remove_money", description="Remove coins from a user (Admin Only)")
    @commands.has_permissions(administrator=True)
    async def remove_money(self, ctx, user: discord.Member, amount: int):
        if amount <= 0:
            return await ctx.send("Amount must be positive.", ephemeral=True)

        # Check balance first
        current = await self.get_balance(user.id)
        if current < amount:
            return await ctx.send(f"User only has {current} coins.", ephemeral=True)

        new_bal = await self.update_balance(user.id, -amount)
        await ctx.send(f"✅ Removed {amount} coins from {user.mention}. New Balance: {new_bal}")

    @commands.hybrid_command(name="pay", description="Give money to another user")
    async def pay(self, ctx, user: discord.Member, amount: int):
        if user.id == ctx.author.id:
            return await ctx.send("You cannot pay yourself.", ephemeral=True)
        if amount <= 0:
            return await ctx.send("Amount must be positive.", ephemeral=True)

        # Check sender balance
        sender_bal = await self.get_balance(ctx.author.id)
        if sender_bal < amount:
            return await ctx.send(f"Insufficient funds. You have {sender_bal} coins.", ephemeral=True)

        # Transfer
        await self.update_balance(ctx.author.id, -amount)
        await self.update_balance(user.id, amount)

        await ctx.send(f"💸 {ctx.author.mention} paid {amount} coins to {user.mention}!")

    # --- PvP Wagers (New v2.3) ---
    @commands.hybrid_group(name="wager", description="Player vs Player Betting")
    async def wager(self, ctx):
        pass

    @wager.command(name="challenge", description="Challenge a user to a wager")
    async def wager_challenge(self, ctx, opponent: discord.Member, amount: int):
        if opponent.bot or opponent.id == ctx.author.id:
            return await ctx.send("Invalid opponent.", ephemeral=True)
        if amount <= 0:
            return await ctx.send("Amount must be positive.", ephemeral=True)

        # Check Challenger Balance
        bal = await self.get_balance(ctx.author.id)
        if bal < amount:
            return await ctx.send(f"Insufficient funds. You have {bal} coins.", ephemeral=True)

        # Create Pending Bet in DB
        # We put Challenger's money in escrow NOW?
        # Plan says "Amount is deducted from A (Escrow)".
        await self.update_balance(ctx.author.id, -amount)

        async with aiosqlite.connect("bot_data.db") as db:
            cursor = await db.execute("""
                INSERT INTO pvp_bets (guild_id, challenger_id, opponent_id, amount, status)
                VALUES (?, ?, ?, ?, 'PENDING')
            """, (ctx.guild.id, ctx.author.id, opponent.id, amount))
            bet_id = cursor.lastrowid
            await db.commit()

        # Send Challenge
        embed = discord.Embed(title="⚔️ Wager Challenge", description=f"{ctx.author.mention} challenges {opponent.mention} to a wager of **{amount}** coins!", color=discord.Color.red())
        view = WagerAcceptView(bet_id, opponent.id, amount, ctx.author.id, self) # Pass self (Cog)
        msg = await ctx.send(f"{opponent.mention}", embed=embed, view=view)
        view.message = msg

    @wager.command(name="cancel", description="Cancel a pending wager (Refund)")
    async def wager_cancel(self, ctx):
        async with aiosqlite.connect("bot_data.db") as db:
            db.row_factory = aiosqlite.Row
            # Find the most recent pending bet by this user
            async with db.execute("SELECT * FROM pvp_bets WHERE challenger_id = ? AND status = 'PENDING' ORDER BY id DESC LIMIT 1", (ctx.author.id,)) as cursor:
                bet = await cursor.fetchone()

            if not bet:
                return await ctx.send("You have no pending wagers to cancel.", ephemeral=True)

            # Refund
            await self.update_balance(ctx.author.id, bet['amount'])

            # Delete
            await db.execute("DELETE FROM pvp_bets WHERE id = ?", (bet['id'],))
            await db.commit()

        await ctx.send(f"✅ Wager #{bet['id']} cancelled. Refunded {bet['amount']} coins.")

    @wager.command(name="resolve", description="Resolve an active wager")
    async def wager_resolve(self, ctx):
        # Find active bets for this user
        async with aiosqlite.connect("bot_data.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM pvp_bets
                WHERE (challenger_id = ? OR opponent_id = ?) AND status = 'ACTIVE'
            """, (ctx.author.id, ctx.author.id)) as cursor:
                bets = await cursor.fetchall()

        if not bets:
            return await ctx.send("You have no active wagers.", ephemeral=True)

        # If multiple, maybe ask which one? For now, list them or handle first.
        # User requested "player 1 proposes... player 2 accepts... locked in until both players select winner".
        # Let's show a dropdown if multiple, or just the first one.
        # Let's use a View to let them pick the winner.

        embed = discord.Embed(title="Active Wagers", color=discord.Color.blue())
        for bet in bets:
            opp_id = bet['opponent_id'] if bet['challenger_id'] == ctx.author.id else bet['challenger_id']
            opp = ctx.guild.get_member(opp_id)
            opp_name = opp.display_name if opp else "Unknown"

            embed.add_field(name=f"Bet #{bet['id']} vs {opp_name}", value=f"Amount: {bet['amount']}", inline=False)

            # Send a view for THIS bet immediately?
            # Or just one view for the first one found?
            # Let's send a resolution view for the first found bet for simplicity, or loops.
            view = WagerResolveView(bet['id'], bet['challenger_id'], bet['opponent_id'], bet['amount'])
            await ctx.send(f"Resolve Wager #{bet['id']} vs {opp_name}", view=view)

from discord.ui import View, Button

class WagerAcceptView(View):
    def __init__(self, bet_id, opponent_id, amount, challenger_id, cog):
        super().__init__(timeout=300)
        self.bet_id = bet_id
        self.opponent_id = opponent_id
        self.amount = amount
        self.challenger_id = challenger_id
        self.cog = cog # Economy Cog instance
        self.message = None

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
    async def accept(self, interaction, button):
        if interaction.user.id != self.opponent_id:
            return await interaction.response.send_message("Not your challenge.", ephemeral=True)

        # Check Opponent Balance
        bal = await self.cog.get_balance(self.opponent_id)
        if bal < self.amount:
            return await interaction.response.send_message("Insufficient funds to accept.", ephemeral=True)

        await self.cog.update_balance(self.opponent_id, -self.amount)

        async with aiosqlite.connect("bot_data.db") as db:
            await db.execute("UPDATE pvp_bets SET status = 'ACTIVE' WHERE id = ?", (self.bet_id,))
            await db.commit()

        embed = discord.Embed(title="⚔️ Wager Accepted!", description=f"Bet #{self.bet_id} is LIVE! Pot: {self.amount * 2}\nUse `/wager resolve` to declare the winner.", color=discord.Color.green())
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red)
    async def decline(self, interaction, button):
        if interaction.user.id != self.opponent_id and interaction.user.id != self.challenger_id:
            return await interaction.response.send_message("Not your challenge.", ephemeral=True)

        # Refund Challenger
        await self.cog.update_balance(self.challenger_id, self.amount)

        async with aiosqlite.connect("bot_data.db") as db:
            await db.execute("DELETE FROM pvp_bets WHERE id = ?", (self.bet_id,))
            await db.commit()

        await interaction.response.edit_message(content="Wager declined/cancelled. Refunded.", embed=None, view=None)
        self.stop()

    async def on_timeout(self):
        # Refund Challenger on Timeout
        await self.cog.update_balance(self.challenger_id, self.amount)

        async with aiosqlite.connect("bot_data.db") as db:
            await db.execute("DELETE FROM pvp_bets WHERE id = ?", (self.bet_id,))
            await db.commit()

        if self.message:
            try:
                await self.message.edit(content="❌ **Challenge Timed Out.** Refunded.", embed=None, view=None)
            except:
                pass

class WagerResolveView(View):
    def __init__(self, bet_id, challenger_id, opponent_id, amount):
        super().__init__(timeout=None) # Persistent-ish
        self.bet_id = bet_id
        self.c_id = challenger_id
        self.o_id = opponent_id
        self.amount = amount

    async def register_vote(self, interaction, voter_id, winner_id):
        col = "challenger_vote" if voter_id == self.c_id else "opponent_vote"

        async with aiosqlite.connect("bot_data.db") as db:
            await db.execute(f"UPDATE pvp_bets SET {col} = ? WHERE id = ?", (winner_id, self.bet_id))
            await db.commit()

            # Check if both voted
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM pvp_bets WHERE id = ?", (self.bet_id,)) as cursor:
                bet = await cursor.fetchone()

        if bet['challenger_vote'] is not None and bet['opponent_vote'] is not None:
            # Resolution
            econ = interaction.client.get_cog("Economy")

            if bet['challenger_vote'] == bet['opponent_vote']:
                # Match
                winner_id = bet['challenger_vote']
                pot = self.amount * 2
                await econ.update_balance(winner_id, pot)

                async with aiosqlite.connect("bot_data.db") as db:
                    await db.execute("UPDATE pvp_bets SET status = 'RESOLVED', winner_id = ? WHERE id = ?", (winner_id, self.bet_id))
                    await db.commit()

                winner = interaction.guild.get_member(winner_id)
                await interaction.channel.send(f"🏆 **Wager #{self.bet_id} Resolved!**\nWinner: {winner.mention if winner else winner_id}\nPayout: {pot} coins!")

            else:
                # Mismatch -> Void
                await econ.update_balance(self.c_id, self.amount)
                await econ.update_balance(self.o_id, self.amount)

                async with aiosqlite.connect("bot_data.db") as db:
                    await db.execute("UPDATE pvp_bets SET status = 'VOID' WHERE id = ?", (self.bet_id,))
                    await db.commit()

                await interaction.channel.send(f"❌ **Wager #{self.bet_id} Dispute!**\nPlayers selected different winners.\nBet VOIDED and refunded.")

            # Disable view
            self.stop()
            # If we could, we would disable buttons on the message, but we might not have the message obj here easily without storing it or using interactions.
            # We can try editing the interaction response if it's the last one.
            try:
                await interaction.response.edit_message(content="Wager Resolved.", view=None)
            except:
                pass
        else:
            await interaction.response.send_message(f"Vote recorded. Waiting for opponent...", ephemeral=True)

    @discord.ui.button(label="I Won", style=discord.ButtonStyle.primary)
    async def i_won(self, interaction, button):
        if interaction.user.id not in [self.c_id, self.o_id]: return
        await self.register_vote(interaction, interaction.user.id, interaction.user.id)

    @discord.ui.button(label="Opponent Won", style=discord.ButtonStyle.secondary)
    async def opp_won(self, interaction, button):
        if interaction.user.id not in [self.c_id, self.o_id]: return
        winner = self.o_id if interaction.user.id == self.c_id else self.c_id
        await self.register_vote(interaction, interaction.user.id, winner)
