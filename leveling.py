import discord
from discord.ext import commands
from discord import ui
import aiosqlite
from PIL import Image, ImageDraw, ImageFont
import io
import requests
import aiohttp
from config_manager import config_manager
import logger

# --- Views for Settings ---

class ColorSelect(ui.Select):
    def __init__(self, target_setting):
        self.target_setting = target_setting # 'card_color' or 'card_bg_color'
        options = [
            discord.SelectOption(label="Blurple (Default)", value="#5865F2", emoji="🟦"),
            discord.SelectOption(label="Green", value="#57F287", emoji="🟩"),
            discord.SelectOption(label="Yellow", value="#FEE75C", emoji="🟨"),
            discord.SelectOption(label="Fuchsia", value="#EB459E", emoji="🏩"),
            discord.SelectOption(label="Red", value="#ED4245", emoji="🟥"),
            discord.SelectOption(label="White", value="#FFFFFF", emoji="⬜"),
            discord.SelectOption(label="Black", value="#000000", emoji="⬛"),
            discord.SelectOption(label="Custom Hex...", value="custom", emoji="🎨"),
        ]
        super().__init__(placeholder=f"Select {target_setting.replace('_', ' ')}...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        if value == "custom":
            await interaction.response.send_modal(HexModal(self.target_setting))
        else:
            await self.update_db(interaction, value)

    async def update_db(self, interaction, value):
        async with aiosqlite.connect("bot_data.db") as db:
             await db.execute(f"""
                INSERT INTO global_users (user_id, {self.target_setting}) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET {self.target_setting} = ?
             """, (interaction.user.id, value, value))
             await db.commit()
        await interaction.response.send_message(f"Updated {self.target_setting} to `{value}`!", ephemeral=True)

class HexModal(ui.Modal, title="Enter Hex Color"):
    def __init__(self, target_setting):
        super().__init__()
        self.target_setting = target_setting
        self.hex_input = ui.TextInput(label="Hex Code (e.g. #FF0000)", placeholder="#FF0000", min_length=4, max_length=7)
        self.add_item(self.hex_input)

    async def on_submit(self, interaction: discord.Interaction):
        value = self.hex_input.value
        if not value.startswith("#"):
            value = "#" + value
        # Basic validation
        try:
            int(value[1:], 16)
        except ValueError:
             await interaction.response.send_message("Invalid Hex Code!", ephemeral=True)
             return

        async with aiosqlite.connect("bot_data.db") as db:
             await db.execute(f"""
                INSERT INTO global_users (user_id, {self.target_setting}) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET {self.target_setting} = ?
             """, (interaction.user.id, value, value))
             await db.commit()
        await interaction.response.send_message(f"Updated {self.target_setting} to `{value}`!", ephemeral=True)

class FontSelect(ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Roboto (Default)", value="default", description="Standard modern font"),
            discord.SelectOption(label="Minecraft (Simulated)", value="minecraft", description="Pixelated style font"),
            discord.SelectOption(label="Serif", value="serif", description="Classic serif font"),
        ]
        super().__init__(placeholder="Select Font...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        async with aiosqlite.connect("bot_data.db") as db:
             await db.execute("""
                INSERT INTO global_users (user_id, card_font) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET card_font = ?
             """, (interaction.user.id, value, value))
             await db.commit()
        await interaction.response.send_message(f"Font updated to `{value}`!", ephemeral=True)

class OpacitySelect(ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="0% (Invisible Overlay)", value="0.0"),
            discord.SelectOption(label="20%", value="0.2"),
            discord.SelectOption(label="40%", value="0.4"),
            discord.SelectOption(label="50% (Default)", value="0.5"),
            discord.SelectOption(label="60%", value="0.6"),
            discord.SelectOption(label="80%", value="0.8"),
            discord.SelectOption(label="100% (Solid)", value="1.0"),
        ]
        super().__init__(placeholder="Select Overlay Opacity...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        value = float(self.values[0])
        async with aiosqlite.connect("bot_data.db") as db:
             await db.execute("""
                INSERT INTO global_users (user_id, card_opacity) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET card_opacity = ?
             """, (interaction.user.id, value, value))
             await db.commit()
        await interaction.response.send_message(f"Overlay opacity updated to `{int(value*100)}%`!", ephemeral=True)

class CropView(ui.View):
    def __init__(self, user_id, url, image_bytes):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.url = url
        self.image_bytes = image_bytes
        self.img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        self.img_w, self.img_h = self.img.size

        # Calculate max initial crop
        # Target Ratio 3.6 (900/250)
        self.target_ratio = 3.6

        # Try max width
        w = self.img_w
        h = int(w / self.target_ratio)
        if h > self.img_h:
            # Width constrained by height
            h = self.img_h
            w = int(h * self.target_ratio)

        self.crop_w = w
        self.crop_h = h

        # Center it
        self.crop_x = (self.img_w - self.crop_w) // 2
        self.crop_y = (self.img_h - self.crop_h) // 2

        self.step = 20 # Pixel step for movement

    def get_file(self):
        # Crop
        crop_box = (self.crop_x, self.crop_y, self.crop_x + self.crop_w, self.crop_y + self.crop_h)
        cropped = self.img.crop(crop_box)
        resized = cropped.resize((900, 250), Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        resized.save(buffer, "PNG")
        buffer.seek(0)
        return discord.File(buffer, filename="preview.png")

    async def update_view(self, interaction):
        f = self.get_file()
        await interaction.response.edit_message(attachments=[f], view=self)

    @ui.button(label="Zoom In", style=discord.ButtonStyle.secondary, row=0)
    async def zoom_in(self, interaction: discord.Interaction, button: ui.Button):
        # Decrease crop size (zooms in on content)
        # Keep center
        cx = self.crop_x + self.crop_w // 2
        cy = self.crop_y + self.crop_h // 2

        new_w = max(100, self.crop_w - 50)
        new_h = int(new_w / self.target_ratio)

        self.crop_w = new_w
        self.crop_h = new_h

        # Recenter
        self.crop_x = cx - self.crop_w // 2
        self.crop_y = cy - self.crop_h // 2
        self.clamp()
        await self.update_view(interaction)

    @ui.button(label="Up", style=discord.ButtonStyle.primary, emoji="⬆️", row=0)
    async def move_up(self, interaction: discord.Interaction, button: ui.Button):
        self.crop_y -= self.step
        self.clamp()
        await self.update_view(interaction)

    @ui.button(label="Zoom Out", style=discord.ButtonStyle.secondary, row=0)
    async def zoom_out(self, interaction: discord.Interaction, button: ui.Button):
        # Increase crop size
        cx = self.crop_x + self.crop_w // 2
        cy = self.crop_y + self.crop_h // 2

        # Max dimensions logic
        # Max width is img_w, BUT max height is img_h
        # w = h * 3.6
        max_w_by_h = int(self.img_h * self.target_ratio)
        max_w = min(self.img_w, max_w_by_h)

        new_w = min(max_w, self.crop_w + 50)
        new_h = int(new_w / self.target_ratio)

        self.crop_w = new_w
        self.crop_h = new_h

        self.crop_x = cx - self.crop_w // 2
        self.crop_y = cy - self.crop_h // 2
        self.clamp()
        await self.update_view(interaction)

    @ui.button(label="Left", style=discord.ButtonStyle.primary, emoji="⬅️", row=1)
    async def move_left(self, interaction: discord.Interaction, button: ui.Button):
        self.crop_x -= self.step
        self.clamp()
        await self.update_view(interaction)

    @ui.button(label="Down", style=discord.ButtonStyle.primary, emoji="⬇️", row=1)
    async def move_down(self, interaction: discord.Interaction, button: ui.Button):
        self.crop_y += self.step
        self.clamp()
        await self.update_view(interaction)

    @ui.button(label="Right", style=discord.ButtonStyle.primary, emoji="➡️", row=1)
    async def move_right(self, interaction: discord.Interaction, button: ui.Button):
        self.crop_x += self.step
        self.clamp()
        await self.update_view(interaction)

    @ui.button(label="Save", style=discord.ButtonStyle.green, row=2)
    async def save(self, interaction: discord.Interaction, button: ui.Button):
        async with aiosqlite.connect("bot_data.db") as db:
             await db.execute("""
                INSERT INTO global_users (user_id, bg_url, bg_crop_x, bg_crop_y, bg_crop_w)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                bg_url = ?, bg_crop_x = ?, bg_crop_y = ?, bg_crop_w = ?
             """, (interaction.user.id, self.url, self.crop_x, self.crop_y, self.crop_w,
                   self.url, self.crop_x, self.crop_y, self.crop_w))
             await db.commit()
        await interaction.response.edit_message(content="Background Image Saved!", view=None, attachments=[])

    def clamp(self):
        # Ensure crop box is within image bounds
        if self.crop_x < 0: self.crop_x = 0
        if self.crop_y < 0: self.crop_y = 0
        if self.crop_x + self.crop_w > self.img_w: self.crop_x = self.img_w - self.crop_w
        if self.crop_y + self.crop_h > self.img_h: self.crop_y = self.img_h - self.crop_h

class ImageModal(ui.Modal, title="Background Image"):
    url_input = ui.TextInput(label="Image URL", placeholder="https://example.com/image.png")

    async def on_submit(self, interaction: discord.Interaction):
        url = self.url_input.value
        # Simple validation
        if not url.startswith("http"):
             await interaction.response.send_message("Please provide a valid URL starting with http/https.", ephemeral=True)
             return

        await interaction.response.defer(ephemeral=True)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    if resp.status != 200:
                        await interaction.followup.send("Failed to download image. Check the URL.", ephemeral=True)
                        return
                    data = await resp.read()

            # Create View
            view = CropView(interaction.user.id, url, data)
            f = view.get_file()
            await interaction.followup.send("Adjust your background image:", file=f, view=view, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"Error processing image: {e}", ephemeral=True)

class RankSettingsView(ui.View):
    def __init__(self, cog):
        super().__init__(timeout=180)
        self.cog = cog
        self.add_item(ColorSelect('card_color')) # Main Color (Accents)
        self.add_item(ColorSelect('card_bg_color')) # Background Color
        self.add_item(FontSelect())
        self.add_item(OpacitySelect())

    @ui.button(label="Set Background Image", style=discord.ButtonStyle.secondary, emoji="🖼️", row=2)
    async def set_bg_image(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(ImageModal())

    @ui.button(label="Show Preview", style=discord.ButtonStyle.primary, emoji="👁️", row=2)
    async def preview(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        # Call the rank generation logic but ephemeral
        await self.cog.generate_card(interaction, interaction.user, ephemeral=True)

    @ui.button(label="Reset to Default", style=discord.ButtonStyle.danger, row=2)
    async def reset(self, interaction: discord.Interaction, button: ui.Button):
        async with aiosqlite.connect("bot_data.db") as db:
             await db.execute("""
                INSERT INTO global_users (user_id, bg_url, card_color, card_bg_color, card_opacity, card_font)
                VALUES (?, NULL, '#7289da', '#2C2F33', 0.5, 'default')
                ON CONFLICT(user_id) DO UPDATE SET
                bg_url=NULL, card_color='#7289da', card_bg_color='#2C2F33', card_opacity=0.5, card_font='default'
             """, (interaction.user.id,))
             await db.commit()
        await interaction.followup.send("Rank card settings reset to default!", ephemeral=True)

# --- Leveling Cog ---

class Leveling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_xp(self, guild_id, user_id):
        async with aiosqlite.connect("bot_data.db") as db:
            async with db.execute("SELECT xp, level FROM user_levels WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)) as cursor:
                row = await cursor.fetchone()
                return row if row else (0, 0)

    async def add_xp(self, guild_id, user_id, amount):
        async with aiosqlite.connect("bot_data.db") as db:
            row = await self.get_xp(guild_id, user_id)
            current_xp, current_level = row

            new_xp = current_xp + amount
            next_level_xp = (current_level + 1) * 100
            new_level = current_level

            while new_xp >= next_level_xp:
                new_level += 1
                next_level_xp = (new_level + 1) * 100

            await db.execute("""
                INSERT INTO user_levels (guild_id, user_id, xp, level) VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET xp = ?, level = ?
            """, (guild_id, user_id, new_xp, new_level, new_xp, new_level))
            await db.commit()

            return new_level > current_level, new_level

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild: return

        # Calculate XP with Rate
        base_xp = 15
        config = await config_manager.get_guild_config(message.guild.id)
        rate = config.get('xp_rate', 1.0)
        final_xp = int(base_xp * rate)

        leveled_up, new_level = await self.add_xp(message.guild.id, message.author.id, final_xp)
        if leveled_up:
            await message.channel.send(f"🎉 {message.author.mention} has reached **Level {new_level}**!")

    def hex_to_rgb(self, hex_code):
        hex_code = hex_code.lstrip('#')
        try:
            return tuple(int(hex_code[i:i+2], 16) for i in (0, 2, 4))
        except:
            return (114, 137, 218) # Default Blurple

    # Separate generation logic to support both command and preview
    async def generate_card(self, ctx_or_interaction, user, ephemeral=False):
        # Determine send method
        send = ctx_or_interaction.send if hasattr(ctx_or_interaction, 'send') else ctx_or_interaction.followup.send
        guild_id = ctx_or_interaction.guild.id if ctx_or_interaction.guild else None

        xp, level = await self.get_xp(guild_id, user.id)

        # Calculate Rank
        rank_pos = 1
        async with aiosqlite.connect("bot_data.db") as db:
             async with db.execute("SELECT COUNT(*) FROM user_levels WHERE guild_id = ? AND xp > ?", (guild_id, xp)) as cursor:
                 rank_pos = (await cursor.fetchone())[0] + 1

        # Fetch Custom Settings
        bg_url = None
        card_color = "#5865F2" # Blurple
        card_bg_color = "#2C2F33" # Dark Gray
        card_opacity = 0.5
        card_font = "default"

        bg_crop_x = 0
        bg_crop_y = 0
        bg_crop_w = 0

        async with aiosqlite.connect("bot_data.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM global_users WHERE user_id = ?", (user.id,)) as cursor:
                profile = await cursor.fetchone()
                if profile:
                    if profile['bg_url']: bg_url = profile['bg_url']
                    if profile['card_color']: card_color = profile['card_color']
                    if profile['card_bg_color']: card_bg_color = profile['card_bg_color']
                    if profile['card_opacity'] is not None: card_opacity = profile['card_opacity']
                    if profile['card_font']: card_font = profile['card_font']

                    # Safe fetch for new columns in case of migration delay/error
                    try:
                        if profile['bg_crop_w']: bg_crop_w = profile['bg_crop_w']
                        if profile['bg_crop_x']: bg_crop_x = profile['bg_crop_x']
                        if profile['bg_crop_y']: bg_crop_y = profile['bg_crop_y']
                    except: pass

        # Generate Image
        try:
            width, height = 900, 250

            # 1. Background
            try:
                if bg_url:
                    # Non-blocking request
                    async with aiohttp.ClientSession() as session:
                        async with session.get(bg_url, timeout=5) as resp:
                            if resp.status == 200:
                                data = await resp.read()
                                bg_image = Image.open(io.BytesIO(data)).convert("RGBA")

                                # Apply Crop if configured
                                if bg_crop_w > 0:
                                    bg_crop_h = int(bg_crop_w / 3.6)
                                    crop_box = (bg_crop_x, bg_crop_y, bg_crop_x + bg_crop_w, bg_crop_y + bg_crop_h)
                                    bg_image = bg_image.crop(crop_box)

                                bg_image = bg_image.resize((width, height), Image.Resampling.LANCZOS)
                                image = bg_image
                            else:
                                image = Image.new("RGBA", (width, height), self.hex_to_rgb(card_bg_color))
                else:
                    image = Image.new("RGBA", (width, height), self.hex_to_rgb(card_bg_color))
            except Exception as e:
                # Fallback if URL fails
                logger.error(f"BG Image Load Error: {e}")
                image = Image.new("RGBA", (width, height), self.hex_to_rgb(card_bg_color))

            draw = ImageDraw.Draw(image)

            # 2. Overlay (Dark Box)
            overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            draw_overlay = ImageDraw.Draw(overlay)

            box_x, box_y, box_w, box_h = 20, 20, 860, 210
            alpha = int(255 * card_opacity)
            draw_overlay.rectangle((box_x, box_y, box_x + box_w, box_y + box_h), fill=(0, 0, 0, alpha))

            image = Image.alpha_composite(image, overlay)
            draw = ImageDraw.Draw(image)

            # 3. Avatar
            avatar_bytes = await user.display_avatar.read()
            avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            avatar = avatar.resize((150, 150))

            mask = Image.new("L", (150, 150), 0)
            draw_mask = ImageDraw.Draw(mask)
            draw_mask.ellipse((0, 0, 150, 150), fill=255)

            border_size = 5
            draw.ellipse((50 - border_size, 50 - border_size, 50 + 150 + border_size, 50 + 150 + border_size), fill=self.hex_to_rgb(card_color))

            image.paste(avatar, (50, 50), mask=mask)

            # 4. Text & Fonts
            text_color = (255, 255, 255)

            try:
                font_large = ImageFont.truetype("Roboto-Bold.ttf", 60)
                font_medium = ImageFont.truetype("Roboto-Regular.ttf", 40)
                font_small = ImageFont.truetype("Roboto-Regular.ttf", 30)
            except:
                font_large = ImageFont.load_default()
                font_medium = ImageFont.load_default()
                font_small = ImageFont.load_default()

            text_x = 230
            draw.text((text_x, 50), str(user.name), font=font_large, fill=text_color)

            stats_text = f"Rank #{rank_pos}   Level {level}"
            draw.text((text_x, 120), stats_text, font=font_medium, fill=text_color)

            next_level_xp = (level + 1) * 100
            current_level_base = level * 100
            needed = next_level_xp - current_level_base
            current_progress = xp - current_level_base

            xp_text = f"{current_progress} / {needed} XP"
            try:
                bbox = font_small.getbbox(xp_text)
                text_w = bbox[2] - bbox[0]
            except:
                text_w = 100

            draw.text((860 - text_w - 20, 170), xp_text, font=font_small, fill=text_color)

            # 5. Progress Bar
            bar_x, bar_y, bar_w, bar_h = 230, 180, 600, 20
            draw.rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), fill=(50, 50, 50))

            percent = max(0, min(1, current_progress / needed)) if needed > 0 else 0
            draw.rectangle((bar_x, bar_y, bar_x + int(bar_w * percent), bar_y + bar_h), fill=self.hex_to_rgb(card_color))

            buffer = io.BytesIO()
            image.save(buffer, "PNG")
            buffer.seek(0)

            await send(file=discord.File(buffer, filename="rank.png"), ephemeral=ephemeral)

        except Exception as e:
            await send(f"Failed to generate rank card: {e}", ephemeral=ephemeral)

    @commands.hybrid_command(name="rank", description="Show your rank card")
    async def rank(self, ctx, user: discord.Member = None):
        user = user or ctx.author
        await self.generate_card(ctx, user)

    @commands.hybrid_command(name="rank_settings", description="Open the Rank Card customization menu")
    async def rank_settings(self, ctx):
        embed = discord.Embed(
            title="🎨 Rank Card Settings",
            description="Customize your rank card appearance using the options below.",
            color=discord.Color.blue()
        )

        view = RankSettingsView(self)
        await ctx.send(embed=embed, view=view)

    @commands.hybrid_command(name="leaderboard", description="Show top 5 active members")
    async def leaderboard(self, ctx):
        guild_id = ctx.guild.id
        async with aiosqlite.connect("bot_data.db") as db:
            async with db.execute("""
                SELECT user_id, xp, level FROM user_levels
                WHERE guild_id = ?
                ORDER BY xp DESC LIMIT 5
            """, (guild_id,)) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            return await ctx.send("No ranked users yet.", ephemeral=True)

        embed = discord.Embed(title=f"📊 {ctx.guild.name} Leaderboard", color=discord.Color.gold())

        for idx, row in enumerate(rows, start=1):
            user_id, xp, level = row
            # Fetch user object (try cache first)
            member = ctx.guild.get_member(user_id)
            name = member.display_name if member else f"User {user_id}"

            embed.add_field(
                name=f"#{idx} {name}",
                value=f"Level {level} • {xp} XP",
                inline=False
            )

        await ctx.send(embed=embed)

    @commands.hybrid_command(name="set_xp_rate", description="Set the XP multiplier (Admin/Owner)")
    async def set_xp_rate(self, ctx, multiplier: float):
        # Check Admin/Owner
        if ctx.author.id != ctx.guild.owner_id and not ctx.author.guild_permissions.administrator:
            return await ctx.send("You need Administrator permissions.", ephemeral=True)

        if multiplier < 0.1:
            return await ctx.send("Multiplier must be at least 0.1.", ephemeral=True)

        await config_manager.update_guild_config(ctx.guild.id, 'xp_rate', multiplier)
        await ctx.send(f"XP Rate set to **{multiplier}x**.")

    @commands.hybrid_command(name="add_xp", description="Add XP to a user (Admin/Mod)")
    @commands.has_permissions(manage_messages=True)
    async def add_xp_command(self, ctx, user: discord.Member, amount: int):
        # Using manage_messages as a proxy for 'Mod' permissions if not using the bot's custom mod role check yet for simple perms
        # But let's check custom mod role too
        # Actually, let's trust discord permissions for now or use the helper if I imported it?
        # Helper 'is_admin_or_mod' is in bot.py, not here.
        # I'll rely on has_permissions(manage_messages=True) + manual check if needed.

        leveled_up, new_level = await self.add_xp(ctx.guild.id, user.id, amount)
        msg = f"Added {amount} XP to {user.mention}."
        if leveled_up:
             msg += f"\n🎉 They reached **Level {new_level}**!"
        await ctx.send(msg)
