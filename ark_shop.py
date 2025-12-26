import discord
from discord.ext import commands
import aiosqlite
import logger
from discord.ui import View, Select
from rcon_adapter import RCONAdapter

class ArkShop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        # Register the persistent view on load
        self.bot.add_view(ArkShopView(self.bot))

    async def get_ark_config(self, guild_id):
        async with aiosqlite.connect("bot_data.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM ark_config WHERE guild_id = ?", (guild_id,)) as cursor:
                return await cursor.fetchone()

    # --- Configuration ---
    @commands.hybrid_group(name="ark", description="Ark Survival Ascended Shop & RCON")
    async def ark(self, ctx):
        pass

    @ark.command(name="config", description="Configure Ark RCON and Shop Channel (Admin)")
    @commands.has_permissions(administrator=True)
    async def ark_config(self, ctx, rcon_ip: str, rcon_port: int, rcon_password: str, channel: discord.TextChannel):
        async with aiosqlite.connect("bot_data.db") as db:
            await db.execute("""
                INSERT OR REPLACE INTO ark_config (guild_id, channel_id, rcon_ip, rcon_port, rcon_password)
                VALUES (?, ?, ?, ?, ?)
            """, (ctx.guild.id, channel.id, rcon_ip, rcon_port, rcon_password))
            await db.commit()

        await ctx.send(f"Ark config updated!\nChannel: {channel.mention}\nRCON: {rcon_ip}:{rcon_port}", ephemeral=True)

    # --- Shop Management ---
    @ark.command(name="add_item", description="Add an item to the Ark Shop (Admin)")
    @commands.has_permissions(administrator=True)
    async def ark_add_item(self, ctx, name: str, price: int, command: str):
        """
        Add an item. Use {steam_id} as a placeholder in the command.
        Example: GiveItemToPlayer {steam_id} ...
        """
        async with aiosqlite.connect("bot_data.db") as db:
            await db.execute("INSERT INTO ark_shop_items (guild_id, name, price, command) VALUES (?, ?, ?, ?)",
                             (ctx.guild.id, name, price, command))
            await db.commit()

        await ctx.send(f"Added item **{name}** for {price} coins.", ephemeral=True)

    @ark.command(name="remove_item", description="Remove an item from the Ark Shop (Admin)")
    @commands.has_permissions(administrator=True)
    async def ark_remove_item(self, ctx, name: str):
        async with aiosqlite.connect("bot_data.db") as db:
            await db.execute("DELETE FROM ark_shop_items WHERE guild_id = ? AND lower(name) = ?",
                             (ctx.guild.id, name.lower()))
            await db.commit()

        await ctx.send(f"Removed item **{name}**.", ephemeral=True)

    # --- User Registration ---
    @commands.hybrid_command(name="registerark", description="Link your Steam ID for the Ark Shop")
    async def register_ark(self, ctx, steam_id: str):
        # Basic validation for Steam ID (usually 17 digits)
        if not steam_id.isdigit():
             return await ctx.send("Steam ID must be numeric.", ephemeral=True)

        async with aiosqlite.connect("bot_data.db") as db:
            # Upsert
            await db.execute("""
                INSERT INTO game_links (user_id, game_key, platform_id) VALUES (?, 'ARK', ?)
                ON CONFLICT(user_id, game_key) DO UPDATE SET platform_id = ?
            """, (ctx.author.id, steam_id, steam_id))
            await db.commit()

        await ctx.send(f"✅ Linked Steam ID **{steam_id}** for Ark.", ephemeral=True)

    # --- Persistent Shop Interface ---
    @ark.command(name="spawn_shop", description="Spawn the persistent shop menu (Admin)")
    @commands.has_permissions(administrator=True)
    async def spawn_shop(self, ctx):
        config = await self.get_ark_config(ctx.guild.id)
        if not config:
            return await ctx.send("Ark config not found. Run `/ark config` first.", ephemeral=True)

        channel = ctx.guild.get_channel(config['channel_id'])
        if not channel:
            return await ctx.send("Configured shop channel not found.", ephemeral=True)

        # Build View
        view = ArkShopView(self.bot)
        embed = discord.Embed(title="🦖 Ark Survival Ascended Shop",
                              description="Select an item below to purchase.\nMake sure you are online in the server!\nYou must be registered via `/registerark`.",
                              color=discord.Color.green())

        await channel.send(embed=embed, view=view)
        await ctx.send("Shop spawned!", ephemeral=True)

class ArkShopView(View):
    def __init__(self, bot):
        super().__init__(timeout=None) # Persistent
        self.bot = bot
        # Ideally, we load items dynamically.
        # But `Select` options are static in `__init__` usually unless we use a callback to populate.
        # For a persistent view to work across restarts, we need a custom_id and we need to re-register it.
        # But if items change, the view needs to update.
        # Solution: The View has a Select Menu that populates its options *when sent*? No, views are stateful.
        # Better: We use a Button "Open Shop" that sends an Ephemeral Message with the current dynamic list.
        # This solves the "too many items" and "updating items" issue gracefully.

    @discord.ui.button(label="🛒 Open Shop", style=discord.ButtonStyle.success, custom_id="ark_shop_open_btn")
    async def open_shop(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Fetch Items
        async with aiosqlite.connect("bot_data.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM ark_shop_items WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
                items = await cursor.fetchall()

        if not items:
            return await interaction.response.send_message("Shop is currently empty.", ephemeral=True)

        # Create Dropdown for this specific interaction
        view = ArkShopPurchaseView(items, self.bot)
        await interaction.response.send_message("Select an item to purchase:", view=view, ephemeral=True)

class ArkShopPurchaseView(View):
    def __init__(self, items, bot):
        super().__init__(timeout=60)
        self.bot = bot
        self.add_item(ArkShopSelect(items, bot))

class ArkShopSelect(Select):
    def __init__(self, items, bot):
        self.bot = bot
        options = []
        # Discord allows max 25 options. We take first 25 for now.
        for item in items[:25]:
            options.append(discord.SelectOption(
                label=f"{item['name']} - {item['price']} coins",
                value=str(item['id']),
                description=f"Cost: {item['price']}"
            ))
        super().__init__(placeholder="Choose an item...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        item_id = int(self.values[0])

        async with aiosqlite.connect("bot_data.db") as db:
            db.row_factory = aiosqlite.Row
            # Get Item
            async with db.execute("SELECT * FROM ark_shop_items WHERE id = ?", (item_id,)) as cursor:
                item = await cursor.fetchone()

            # Get Config
            async with db.execute("SELECT * FROM ark_config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
                config = await cursor.fetchone()

            # Get User Link
            async with db.execute("SELECT platform_id FROM game_links WHERE user_id = ? AND game_key = 'ARK'", (interaction.user.id,)) as cursor:
                link = await cursor.fetchone()

        if not item: return await interaction.response.send_message("Item no longer exists.", ephemeral=True)
        if not config: return await interaction.response.send_message("Ark RCON not configured.", ephemeral=True)
        if not link: return await interaction.response.send_message("You are not registered! Use `/registerark <steam_id>`.", ephemeral=True)

        steam_id = link['platform_id']
        price = item['price']

        # Check Balance (Using Economy Cog)
        economy = self.bot.get_cog("Economy")
        if not economy: return await interaction.response.send_message("Economy system offline.", ephemeral=True)

        bal = await economy.get_balance(interaction.user.id)
        if bal < price:
            return await interaction.response.send_message(f"Insufficient funds. You have {bal} coins.", ephemeral=True)

        # Process Transaction
        await interaction.response.defer(ephemeral=True) # RCON might take a second

        # Deduct Money
        await economy.update_balance(interaction.user.id, -price)

        # Send RCON
        command = item['command'].replace("{steam_id}", steam_id)

        adapter = RCONAdapter(config['rcon_ip'], config['rcon_port'], config['rcon_password'])
        response = await adapter.send_command(command)

        # Check for error (Adapter returns "Error: ..." on exception)
        if response.startswith("Error:"):
            # Refund
            await economy.update_balance(interaction.user.id, price)
            logger.error(f"Ark Shop Error (Refunded): User {interaction.user.id}. CMD: {command}. Error: {response}")
            await interaction.followup.send(f"❌ Purchase failed. The server could not be reached. You have been refunded.\nError: `{response}`")
            return

        # Logging
        logger.info(f"Ark Shop Buy: User {interaction.user.id} ({steam_id}) bought {item['name']}. CMD: {command}. RESP: {response}")

        # Clean up response for user
        display_response = response
        if response == "Command Sent (No Output)" or "Server received, But no response" in response:
            display_response = "Command Sent (No output from server)"

        await interaction.followup.send(f"✅ Purchased **{item['name']}**!\nServer Response: `{display_response}`")
