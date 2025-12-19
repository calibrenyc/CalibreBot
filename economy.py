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
            role = ctx.guild.get_role(item['role_id'])
            role_name = role.name if role else "Deleted Role"
            embed.add_field(name=f"{item['name']} - {item['price']} coins", value=f"Reward: {role_name}\n{item['description']}", inline=False)
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

        role = ctx.guild.get_role(item['role_id'])
        if not role: return await ctx.send("Role associated with this item no longer exists.")

        await self.update_balance(ctx.author.id, -item['price'])
        try:
            await ctx.author.add_roles(role, reason="Bought from shop")
            await ctx.send(f"You bought **{item['name']}** and received the {role.name} role!")
        except:
            await self.update_balance(ctx.author.id, item['price']) # Refund
            await ctx.send("Failed to assign role (I might lack permissions). Refunded.")

    @shop.command(name="add", description="Add an item to the shop (Admin)")
    @commands.has_permissions(administrator=True)
    async def shop_add(self, ctx, name: str, price: int, role: discord.Role, description: str = "No description"):
        async with aiosqlite.connect("bot_data.db") as db:
            await db.execute("INSERT INTO shop_items (guild_id, name, price, role_id, description) VALUES (?, ?, ?, ?, ?)",
                             (ctx.guild.id, name, price, role.id, description))
            await db.commit()
        await ctx.send(f"Added {name} to shop.")

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
