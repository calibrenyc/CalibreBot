import os
import discord
from discord.ext import commands
from discord.ui import Select, View
from dotenv import load_dotenv
import scrapers
import asyncio
import random
import json
import subprocess
import shutil
import sys
from config_manager import config_manager
from database import db_manager
import logger

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
# Global env vars are now deprecated in favor of guild config,
# but we keep OWNER_ROLE_ID as a fallback or for global admin commands.
OWNER_ROLE_ID = os.getenv('OWNER_ROLE_ID')

BOT_VERSION = "2.1.3"

# Setup Bot
class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True # Required for Member updates/joins
        intents.voice_states = True # Required for Voice tracking

        # Prefix '!' OR mentioning the bot
        # Disable default help to allow custom help command
        super().__init__(command_prefix=commands.when_mentioned_or("!"), intents=intents, help_command=None)

    async def setup_hook(self):
        # Initialize DB
        await db_manager.init_db()
        await db_manager.migrate_from_json()

        # Sync slash commands globally
        await self.tree.sync()
        logger.success(f"Commands synced. Bot Version: {BOT_VERSION}")

bot = MyBot()

# Helper to check permissions (Async now)
async def is_admin_or_mod(obj):
    """
    Checks if the user executing the command (Context or Interaction) is an Admin or Mod.
    obj: can be discord.Interaction or commands.Context
    """
    user = obj.author if isinstance(obj, commands.Context) else obj.user
    guild = obj.guild

    if not guild:
        return False # No permissions in DMs usually

    # Check Administrator Permission
    if isinstance(obj, commands.Context):
        if obj.author.guild_permissions.administrator:
            return True
    else:
        if obj.permissions.administrator:
            return True

    # Check Configured Mod Roles via DB
    config = await config_manager.get_guild_config(guild.id)
    mod_roles = config.get('mod_roles', [])

    if mod_roles:
        for role in user.roles:
            if role.id in mod_roles:
                return True

    # Fallback
    if OWNER_ROLE_ID:
        try:
            if any(r.id == int(OWNER_ROLE_ID) for r in user.roles):
                return True
        except:
            pass

    return False

async def perform_update(interaction_or_ctx):
    """
    Handles the full update sequence: Backup, Git Pull, Restore, Restart.
    """
    # Determine context for sending messages
    is_ctx = isinstance(interaction_or_ctx, commands.Context)

    async def send_msg(content):
        if is_ctx:
            await interaction_or_ctx.send(content)
        else:
            if not interaction_or_ctx.response.is_done():
                await interaction_or_ctx.response.send_message(content, ephemeral=False) # Public message so we can see logs
            else:
                await interaction_or_ctx.followup.send(content, ephemeral=False)

    await send_msg("Checking for updates...")
    logger.info("Starting update sequence...")

    # Helper to run shell commands
    async def run_cmd(cmd):
        logger.debug(f"[Update DEBUG] Executing: {cmd}")
        try:
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            output = stdout.decode().strip()
            error = stderr.decode().strip()

            if output: logger.debug(f"[stdout] {output}")
            if error: logger.error(f"[stderr] {error}")

            return process.returncode, output, error
        except Exception as e:
            logger.error(f"[Update DEBUG] Error in run_cmd: {e}")
            raise e

    try:
        # 1. Backup Guild Config & Database
        logger.info("Backing up data...")
        config_backup_path = "guild_configs.json.bak"
        db_backup_path = "bot_data.db.bak"
        has_config_backup = False
        has_db_backup = False

        if os.path.exists("guild_configs.json"):
            shutil.copy2("guild_configs.json", config_backup_path)
            has_config_backup = True
            logger.info("Backed up guild_configs.json")

        if os.path.exists("bot_data.db"):
            shutil.copy2("bot_data.db", db_backup_path)
            has_db_backup = True
            logger.info("Backed up bot_data.db")

        # 2. Git Operations
        # We assume origin is set up correctly in the environment

        # Git Fetch
        await send_msg("Fetching origin...")
        code, out, err = await run_cmd(f"git fetch origin")
        if code != 0:
             await send_msg(f"Git fetch failed: {err}")
             # Attempt repair?
             # For now, proceed or fail? Fails usually mean repo broken.
             # We try to reset anyway.

        # Git Reset
        await send_msg("Resetting to origin/main...")
        code, out, err = await run_cmd("git reset --hard origin/main")
        if code != 0:
             await send_msg(f"Git reset failed: {err}")
             return

        # Git Pull
        await send_msg("Pulling origin main...")
        code, out, err = await run_cmd("git pull origin main")
        if code != 0:
             await send_msg(f"Git pull failed: {err}")
             return

        await send_msg(f"Git Output:\n```\n{out}\n```")

        # 3. Restore Data
        logger.info("Restoring data...")
        if has_config_backup and os.path.exists(config_backup_path):
            shutil.move(config_backup_path, "guild_configs.json")
            logger.info("Restored guild_configs.json")

        if has_db_backup and os.path.exists(db_backup_path):
            shutil.move(db_backup_path, "bot_data.db")
            logger.info("Restored bot_data.db")

        # 4. Save Update State for Post-Restart Notification
        channel_id = interaction_or_ctx.channel.id
        state = {
            "updated": True,
            "channel_id": channel_id,
            "version": BOT_VERSION # Old version, new one will be loaded next
        }
        with open("update_status.json", "w") as f:
            json.dump(state, f)

        # 5. Restart
        await send_msg("Restarting...")
        logger.warning("Closing bot to trigger restart loop...")
        await bot.close()

    except Exception as e:
        logger.error(f"Update failed: {e}")
        await send_msg(f"Update failed with exception: {e}")

@bot.tree.command(name="checkupdate", description="Check for updates and optionally update the bot")
async def check_update(interaction: discord.Interaction):
    # Check permissions (Admins only)
    if not await is_admin_or_mod(interaction): # This checks mod roles too, maybe restrict to Admin?
        # Usually updates are owner/admin only.
        if not interaction.user.guild_permissions.administrator and interaction.user.id != interaction.guild.owner_id:
             return await interaction.response.send_message("You need Administrator permissions to update the bot.", ephemeral=True)

    await interaction.response.defer()

    # Check for updates
    try:
        # Run git fetch
        process = await asyncio.create_subprocess_shell(
            "git fetch origin",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        await process.communicate()

        # Check status
        # git rev-list --count HEAD..origin/main
        process = await asyncio.create_subprocess_shell(
            "git rev-list --count HEAD..origin/main",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, _ = await process.communicate()
        count = stdout.decode().strip()

        if count and count.isdigit() and int(count) > 0:
            # Update available
            # We need to hook into the view logic.
            # Re-implementing a simple inline view here for clarity
            class UpdateConfirmView(View):
                def __init__(self):
                    super().__init__(timeout=60)

                @discord.ui.button(label="Yes", style=discord.ButtonStyle.green)
                async def confirm(self, i: discord.Interaction, button: discord.ui.Button):
                    if i.user != interaction.user: return
                    await i.response.send_message("Starting update...", ephemeral=True)
                    await perform_update(interaction) # Using original interaction context
                    self.stop()

                @discord.ui.button(label="No", style=discord.ButtonStyle.red)
                async def cancel(self, i: discord.Interaction, button: discord.ui.Button):
                    if i.user != interaction.user: return
                    await i.response.edit_message(content="Update cancelled.", view=None)
                    self.stop()

            await interaction.followup.send(f"Update available! ({count} commits behind). Do you want to update?", view=UpdateConfirmView())

        else:
            await interaction.followup.send("Bot is up to date.")

    except Exception as e:
        await interaction.followup.send(f"Failed to check for updates: {e}")

class YesNoView(View):
    def __init__(self, ctx):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.value = None

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("Not your command.", ephemeral=True)
        self.value = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="No", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("Not your command.", ephemeral=True)
        self.value = False
        self.stop()
        await interaction.response.defer()

class ThreadExistsView(View):
    def __init__(self, thread, user, link_content):
        super().__init__()
        self.thread = thread
        self.user = user
        self.link_content = link_content

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.green)
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # Post in the thread
            await self.thread.send(f"{self.user.mention} Here is the link you requested:\n{self.link_content}")

            # Clear the message
            try:
                await interaction.response.defer()
                if interaction.message:
                    await interaction.message.delete()
                else:
                    await interaction.delete_original_response()
            except Exception as e:
                # Fallback if delete fails
                try:
                    await interaction.followup.edit_message(message_id=interaction.message.id, content=f"Posted in {self.thread.mention}.", view=None)
                except:
                    pass

        except Exception as e:
            try:
                 await interaction.followup.send(f"Failed to post in thread: {e}", ephemeral=True)
            except:
                pass

    @discord.ui.button(label="No", style=discord.ButtonStyle.red)
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer()
            if interaction.message:
                await interaction.message.delete()
            else:
                await interaction.delete_original_response()
        except Exception:
            try:
                await interaction.followup.edit_message(message_id=interaction.message.id, content="Request cancelled.", view=None)
            except:
                pass

class SearchResultSelect(Select):
    def __init__(self, results, original_interaction_user):
        # Limit to 24 options to leave room for "None of the above" (Discord limit 25)
        options = []
        for i, res in enumerate(results[:24]):
            # Truncate title if too long
            label = res['title'][:95] + "..." if len(res['title']) > 95 else res['title']
            description = f"Source: {res['source']}"
            options.append(discord.SelectOption(
                label=label, 
                description=description, 
                value=str(i)
            ))
        
        # Add "None of the above" option
        options.append(discord.SelectOption(
            label="None of the options above",
            description="Search again with a specific name",
            value="none_of_above",
            emoji="❌"
        ))

        super().__init__(placeholder="Select a game to create a thread...", min_values=1, max_values=1, options=options)
        self.results = results
        self.original_user = original_interaction_user

    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
            selected_value = self.values[0]

            # Handle "None of the above"
            if selected_value == "none_of_above":
                # Delete the original dropdown message to clean up
                if interaction.message:
                    await interaction.message.delete()
                else:
                    await interaction.delete_original_response()

                # Send prompt for new search
                await interaction.followup.send(
                    f"{self.original_user.mention} Please type the **exact** game title you are looking for below.",
                    ephemeral=True
                )

                def check(m):
                    return m.author == self.original_user and m.channel == interaction.channel

                try:
                    # Wait for user input (30 seconds timeout)
                    msg = await bot.wait_for('message', check=check, timeout=30.0)

                    # Delete the user's input message to keep channel clean
                    try:
                        await msg.delete()
                    except:
                        pass

                    # Trigger search again with new query
                    new_query = msg.content
                    await perform_search(interaction, new_query, self.original_user)

                except asyncio.TimeoutError:
                    await interaction.followup.send("Search timed out. Please try again.", ephemeral=True)
                return

            selected_index = int(selected_value)
            selected_result = self.results[selected_index]
            
            # Truncate title to 100 chars for Discord Thread Name limit
            thread_name = selected_result['title'][:100]

            # --- Get Configured Destination Channel ---
            guild_id = interaction.guild_id
            config = await config_manager.get_guild_config(guild_id)
            forum_channel_id = config.get('forum_channel_id')

            destination_channel = None
            
            if forum_channel_id:
                try:
                    fetched_channel = bot.get_channel(int(forum_channel_id))
                    if fetched_channel:
                        destination_channel = fetched_channel
                    else:
                        # Attempt to fetch if not in cache
                        try:
                            fetched_channel = await bot.fetch_channel(int(forum_channel_id))
                            destination_channel = fetched_channel
                        except:
                            logger.error(f"Could not fetch FORUM_CHANNEL_ID {forum_channel_id}")
                except ValueError:
                    logger.error(f"Invalid FORUM_CHANNEL_ID: {forum_channel_id}")
            
            # If no forum channel configured, fallback to current channel IF allowed?
            # User requirement 3 says: "if no configured channel is set it will alert you... and not post anywhere"
            if not destination_channel:
                 await log_error(interaction.guild, f"User {interaction.user} tried to create a thread but no Forum Channel is configured.")
                 await interaction.followup.send("Error: No Forum Channel configured for this server. Please contact an admin.", ephemeral=True)
                 return

            # --- SCAN FOR EXISTING THREADS ---
            existing_thread = None

            # 1. Check active threads
            if hasattr(destination_channel, 'threads'):
                for t in destination_channel.threads:
                    if t.name == thread_name:
                        existing_thread = t
                        break

            # 2. Check archived threads (if not found in active)
            if not existing_thread and hasattr(destination_channel, 'archived_threads'):
                async for t in destination_channel.archived_threads(limit=None):
                    if t.name == thread_name:
                        existing_thread = t
                        break

            if existing_thread:
                # Ask user for confirmation
                view = ThreadExistsView(existing_thread, self.original_user, selected_result['link'])
                await interaction.followup.send(
                    content=f"A thread for '{selected_result['title']}' already exists: {existing_thread.mention}.\nIs this the game you are looking for?",
                    view=view,
                    ephemeral=True
                )
                return

            # --- CREATE NEW THREAD ---
            logger.info(f"Creating thread for '{thread_name}' in {destination_channel.name} ({destination_channel.type})...")
            
            thread = None
            message_content = f"{self.original_user.mention} Here is the link you requested:\n{selected_result['link']}"

            if isinstance(destination_channel, discord.ForumChannel):
                # Forum Channel creation
                thread_with_message = await destination_channel.create_thread(
                    name=thread_name,
                    content=message_content
                )
                thread = thread_with_message.thread
            
            elif isinstance(destination_channel, discord.TextChannel):
                # Text Channel creation
                thread = await destination_channel.create_thread(
                    name=thread_name,
                    type=discord.ChannelType.public_thread,
                    auto_archive_duration=1440
                )
                # Send the message inside the new thread
                await thread.send(content=message_content)
                
            else:
                 await interaction.followup.send(f"Cannot create threads in channel type: {destination_channel.type}", ephemeral=True)
                 return

            # Cleanup: Delete the dropdown message to keep the channel clean
            try:
                # If it's a regular message (e.g. from !search)
                if interaction.message:
                    await interaction.message.delete()
                else:
                    # If it's ephemeral or otherwise special, edit it away
                    await interaction.followup.edit_message(message_id=interaction.message.id, content="Request fulfilled.", view=None)
            except Exception as e:
                # Fallback if delete fails (e.g. ephemeral permissions or state)
                try:
                    await interaction.followup.edit_message(message_id=interaction.message.id, content="Request fulfilled.", view=None)
                except:
                    pass
            
        except Exception as e:
            logger.error(f"Error in callback: {e}")
            try:
                await interaction.followup.send(f"Failed to create thread: {e}", ephemeral=True)
            except:
                pass

class SearchView(View):
    def __init__(self, results, original_user):
        super().__init__()
        self.add_item(SearchResultSelect(results, original_user))

async def log_audit(guild, message, color=discord.Color.blue()):
    """
    Logs an action to the configured log channel.
    """
    if not guild: return
    config = await config_manager.get_guild_config(guild.id)
    log_channel_id = config.get('log_channel_id')

    if log_channel_id:
        try:
            channel = guild.get_channel(int(log_channel_id))
            if channel:
                embed = discord.Embed(description=message, color=color, timestamp=discord.utils.utcnow())
                await channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Failed to log to channel {log_channel_id}: {e}")

# Legacy alias
async def log_error(guild, message):
    await log_audit(guild, f"**Error:** {message}", discord.Color.red())

async def perform_search(interaction_or_ctx, query, user):
    """
    Shared search logic to be used by the command and the retry flow.
    interaction_or_ctx: can be Context (from command) or Interaction (from retry)
    """
    # Determine context
    is_ctx = isinstance(interaction_or_ctx, commands.Context)
    guild_id = interaction_or_ctx.guild.id if interaction_or_ctx.guild else None

    # Permission Check: Allowed Channels
    if guild_id:
        config = await config_manager.get_guild_config(guild_id)
        allowed_channels = config.get('allowed_search_channels', [])

        current_channel_id = interaction_or_ctx.channel.id

        # Rule: If allowed list is NOT empty, strict enforcement.
        # If allowed list IS empty, should we allow?
        # Requirement 3 implies "if no configured channel is set... not post anywhere".
        # So if list is empty, default to BLOCK (unless Admin setup needed?)
        # Let's say if list is empty, BLOCK.

        if not allowed_channels:
             # Check if we should warn
             if await is_admin_or_mod(interaction_or_ctx):
                 # Admin running in unconfigured server -> Allow? Or Warn?
                 # Better to block and tell them to setup.
                 pass

             msg = "Search is not enabled in any channel on this server. Please ask an admin to configure the bot."
             if is_ctx: await interaction_or_ctx.send(msg)
             else:
                 if not interaction_or_ctx.response.is_done():
                     await interaction_or_ctx.response.send_message(msg, ephemeral=True)
                 else:
                     await interaction_or_ctx.followup.send(msg, ephemeral=True)

             await log_error(interaction_or_ctx.guild, f"Search attempted by {user} but no allowed channels configured.")
             return

        if current_channel_id not in allowed_channels:
             msg = "Command not allowed in this channel."
             if is_ctx: await interaction_or_ctx.send(msg)
             else:
                 if not interaction_or_ctx.response.is_done():
                     await interaction_or_ctx.response.send_message(msg, ephemeral=True)
                 else:
                     await interaction_or_ctx.followup.send(msg, ephemeral=True)
             return

    # Helper to send messages appropriately
    async def send_msg(content, view=None, ephemeral=True):
        if is_ctx:
             if view:
                 await interaction_or_ctx.send(content, view=view)
             else:
                 msg = await interaction_or_ctx.send(content)
                 # Auto-delete plain messages after delay if in public channel
                 await asyncio.sleep(5)
                 try: await msg.delete()
                 except: pass
        else:
             # It's an interaction
             if not interaction_or_ctx.response.is_done():
                 await interaction_or_ctx.response.send_message(content, view=view, ephemeral=ephemeral)
             else:
                 await interaction_or_ctx.followup.send(content, view=view, ephemeral=ephemeral)

    logger.info(f"Performing search for '{query}'...")

    try:
        # Run scrapers
        # Note: We need 'bot' here. Since this is outside class, we use the global 'bot' instance.
        online_fix_results = await bot.loop.run_in_executor(None, scrapers.search_online_fix, query)
        fitgirl_results = await bot.loop.run_in_executor(None, scrapers.search_fitgirl, query)

        all_results = online_fix_results + fitgirl_results
        logger.info(f"Total results found: {len(all_results)}")

        # Filter Logic
        strict_results = []
        clean_query = query.strip().lower()

        for res in all_results:
            if clean_query in res['title'].lower():
                strict_results.append(res)

        final_results = []
        msg_content = ""

        if strict_results:
            final_results = strict_results
            msg_content = f"Found {len(final_results)} results for '{query}':"
        elif all_results:
            final_results = all_results
            msg_content = f"Hey here are similar titles found with your search '{query}':"
        else:
             # No results at all
            await send_msg(f"No results found for '{query}'.")
            return

        # Pass user so we know who to tag in the thread
        view = SearchView(final_results, user)
        await send_msg(msg_content, view=view)

        logger.success("Response sent to user.")

    except Exception as e:
        logger.error(f"Error during search: {e}")
        await send_msg(f"An error occurred while searching: {e}")

@bot.event
async def on_ready():
    logger.success(f'Logged in as {bot.user} (ID: {bot.user.id})')
    await bot.change_presence(activity=discord.Game(name="in Calibre's Brain"))

    # Check for update status
    if os.path.exists("update_status.json"):
        try:
            with open("update_status.json", "r") as f:
                data = json.load(f)

            if data.get("updated"):
                channel_id = data.get("channel_id")
                if channel_id:
                    channel = bot.get_channel(channel_id)
                    if channel:
                        await channel.send(f"Update complete! Current Version: {BOT_VERSION}")

            os.remove("update_status.json")
        except Exception as e:
            logger.error(f"Error processing update status: {e}")

    # Send startup message to all configured log channels
    for guild in bot.guilds:
        try:
            await log_audit(guild, "**Bot is alive!** Startup complete.", discord.Color.green())
        except Exception:
            pass

# --- SETUP WIZARD ---
class RoleSelect(Select):
    def __init__(self, placeholder, callback_func):
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=[])
        self.callback_func = callback_func

    async def callback(self, interaction: discord.Interaction):
        await self.callback_func(interaction, self.values[0])

class RoleSelectView(View):
    def __init__(self, ctx, roles, callback_func):
        super().__init__(timeout=120)
        self.ctx = ctx

        # Create Select Menu
        # Discord limits select options to 25. We take top 25 roles (excluding @everyone)
        options = []
        for role in roles[:25]:
            options.append(discord.SelectOption(label=role.name, value=str(role.id)))

        select = RoleSelect("Select a role...", callback_func)
        select.options = options
        self.add_item(select)

class SetupWizard:
    def __init__(self, ctx: commands.Context):
        self.ctx = ctx
        self.guild = ctx.guild
        self.step = 1

    async def start(self):
        await self.ask_owner_role()

    async def ask_owner_role(self):
        # Filter roles (exclude managed/bot roles if desired, but keeping simple)
        roles = [r for r in self.guild.roles if not r.is_default() and not r.is_bot_managed()]
        roles.sort(key=lambda r: r.position, reverse=True)

        view = RoleSelectView(self.ctx, roles, self.set_owner_role)
        await self.ctx.send("**Step 1/4:** Select the **Owner Role** for the bot configuration.", view=view)

    async def set_owner_role(self, interaction: discord.Interaction, role_id):
        await interaction.response.defer()
        # Save owner role (using add_mod_roles logic for now as owner implies mod)
        # Assuming we just treat owner role as a super-mod or store separate if config supports
        # Config manager currently has 'mod_roles'. Let's add it there for permission consistency
        await config_manager.add_to_list(self.guild.id, 'mod_roles', int(role_id))

        # Also store explicitly if needed, but config_manager generic update works
        await config_manager.update_guild_config(self.guild.id, 'owner_role_id', int(role_id))

        await interaction.edit_original_response(content=f"Owner Role set to <@&{role_id}>.", view=None)
        await self.ask_mod_role()

    async def ask_mod_role(self):
        roles = [r for r in self.guild.roles if not r.is_default() and not r.is_bot_managed()]
        roles.sort(key=lambda r: r.position, reverse=True)

        view = RoleSelectView(self.ctx, roles, self.set_mod_role)
        await self.ctx.send("**Step 2/4:** Select the **Moderator Role**.", view=view)

    async def set_mod_role(self, interaction: discord.Interaction, role_id):
        await interaction.response.defer()
        await config_manager.add_to_list(self.guild.id, 'mod_roles', int(role_id))
        await interaction.edit_original_response(content=f"Moderator Role set to <@&{role_id}>.", view=None)
        await self.ask_create_channels()

    async def ask_create_channels(self):
        view = YesNoView(self.ctx)

        # Define callbacks for Yes/No view to proceed
        # We need to monkey-patch or handle wait() manually.
        # Easier to just wait() on the view.
        msg = await self.ctx.send("**Step 3/4:** Do you want to automatically create a **request channel** and **forum**?", view=view)
        await view.wait()

        if view.value:
            # YES - Create channels
            try:
                cat = await self.guild.create_category("Game Bot")
                req = await self.guild.create_text_channel("game-requests", category=cat)
                forum = await self.guild.create_forum_channel("Game Threads", category=cat)

                await config_manager.update_guild_config(self.guild.id, 'forum_channel_id', forum.id)
                await config_manager.add_to_list(self.guild.id, 'allowed_search_channels', req.id)

                await self.ctx.send(f"Created {req.mention} and {forum.mention}.")
            except Exception as e:
                await self.ctx.send(f"Failed to create channels: {e}")
        else:
            await self.ctx.send("Skipping channel creation.")

        await self.ask_log_channel()

    async def ask_log_channel(self):
        view = YesNoView(self.ctx)
        msg = await self.ctx.send("**Step 4/4:** Do you want to create a private **log channel**?", view=view)
        await view.wait()

        if view.value:
            try:
                # Get Configured Roles for permissions
                config = await config_manager.get_guild_config(self.guild.id)
                mod_roles = config.get('mod_roles', [])
                owner_role_id = config.get('owner_role_id')

                overwrites = {
                    self.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    self.guild.me: discord.PermissionOverwrite(read_messages=True)
                }

                # Add overwrites for mods/owner
                for rid in mod_roles:
                    role = self.guild.get_role(rid)
                    if role: overwrites[role] = discord.PermissionOverwrite(read_messages=True)

                cat = discord.utils.get(self.guild.categories, name="Game Bot")
                log_chan = await self.guild.create_text_channel("bot-logs", category=cat, overwrites=overwrites)

                await config_manager.update_guild_config(self.guild.id, 'log_channel_id', log_chan.id)
                await self.ctx.send(f"Created private log channel: {log_chan.mention}")
            except Exception as e:
                await self.ctx.send(f"Failed to create log channel: {e}")
        else:
            await self.ctx.send("Skipping log channel.")

        await self.finish()

    async def finish(self):
        await self.ctx.send("✅ **Setup Complete!**\nYou can further configure the bot using `/config` commands.")
        await log_audit(self.guild, f"**Setup Wizard** completed by {self.ctx.author.mention}.", discord.Color.green())

@bot.hybrid_command(name="setup", description="Interactive setup wizard (Server Owner only)")
async def setup(ctx: commands.Context):
    # Check Server Owner
    if ctx.author.id != ctx.guild.owner_id:
        await ctx.send("Only the **Server Owner** can run this command.", ephemeral=True)
        return

    await log_audit(ctx.guild, f"**Setup Wizard** started by {ctx.author.mention}.")
    wizard = SetupWizard(ctx)
    await wizard.start()

# --- CONFIG GROUP ---
class ConfigGroup(commands.GroupCog, name="config"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if await is_admin_or_mod(interaction):
            return True
        await interaction.response.send_message("You do not have permission to use config commands.", ephemeral=True)
        return False

    @discord.app_commands.command(name="allow", description="Allow searching in a text channel")
    async def allow(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await config_manager.add_to_list(interaction.guild_id, 'allowed_search_channels', channel.id)
        await interaction.response.send_message(f"Added {channel.mention} to allowed search channels.", ephemeral=True)
        await log_audit(interaction.guild, f"{interaction.user.mention} allowed search in {channel.mention}.")

    @discord.app_commands.command(name="deny", description="Disallow searching in a text channel")
    async def deny(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await config_manager.remove_from_list(interaction.guild_id, 'allowed_search_channels', channel.id)
        await interaction.response.send_message(f"Removed {channel.mention} from allowed search channels.", ephemeral=True)
        await log_audit(interaction.guild, f"{interaction.user.mention} disallowed search in {channel.mention}.")

    @discord.app_commands.command(name="forum", description="Set the forum channel for game threads")
    async def forum(self, interaction: discord.Interaction, channel: discord.ForumChannel):
        await config_manager.update_guild_config(interaction.guild_id, 'forum_channel_id', channel.id)
        await interaction.response.send_message(f"Forum channel set to {channel.mention}.", ephemeral=True)
        await log_audit(interaction.guild, f"{interaction.user.mention} set Forum Channel to {channel.mention}.")

    @discord.app_commands.command(name="logs", description="Set the log channel for bot errors")
    async def logs(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await config_manager.update_guild_config(interaction.guild_id, 'log_channel_id', channel.id)
        await interaction.response.send_message(f"Log channel set to {channel.mention}.", ephemeral=True)
        # Log to the new channel
        await log_audit(interaction.guild, f"{interaction.user.mention} set Log Channel to {channel.mention}.")

    @discord.app_commands.command(name="add_mod", description="Add a role that can manage bot config")
    async def add_mod(self, interaction: discord.Interaction, role: discord.Role):
        await config_manager.add_to_list(interaction.guild_id, 'mod_roles', role.id)
        await interaction.response.send_message(f"Added {role.mention} as a moderator role.", ephemeral=True)
        await log_audit(interaction.guild, f"{interaction.user.mention} added Mod Role {role.mention}.")

    @discord.app_commands.command(name="remove_mod", description="Remove a moderator role")
    async def remove_mod(self, interaction: discord.Interaction, role: discord.Role):
        await config_manager.remove_from_list(interaction.guild_id, 'mod_roles', role.id)
        await interaction.response.send_message(f"Removed {role.mention} from moderator roles.", ephemeral=True)
        await log_audit(interaction.guild, f"{interaction.user.mention} removed Mod Role {role.mention}.")

    @discord.app_commands.command(name="muted_role", description="Set the role to use for muting users")
    async def muted_role(self, interaction: discord.Interaction, role: discord.Role):
        await config_manager.update_guild_config(interaction.guild_id, 'muted_role_id', role.id)
        await interaction.response.send_message(f"Muted role set to {role.mention}.", ephemeral=True)
        await log_audit(interaction.guild, f"{interaction.user.mention} set Muted Role to {role.mention}.")

    @discord.app_commands.command(name="create_mute", description="Create a new Muted role with permissions")
    async def create_mute(self, interaction: discord.Interaction):
        # Check if already configured
        config = await config_manager.get_guild_config(interaction.guild_id)
        existing_id = config.get('muted_role_id')

        if existing_id:
            # Check if role actually exists
            role = interaction.guild.get_role(existing_id)
            if role:
                 # Prompt user
                 class RemoveConfigView(discord.ui.View):
                     def __init__(self, original_interaction):
                         super().__init__(timeout=60)
                         self.original_interaction = original_interaction
                         self.value = None

                     @discord.ui.button(label="Yes, Remove Config", style=discord.ButtonStyle.red)
                     async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
                         if interaction.user != self.original_interaction.user:
                             return await interaction.response.send_message("Not your command.", ephemeral=True)
                         self.value = True
                         self.stop()
                         await interaction.response.defer()

                     @discord.ui.button(label="No, Cancel", style=discord.ButtonStyle.gray)
                     async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
                         if interaction.user != self.original_interaction.user:
                             return await interaction.response.send_message("Not your command.", ephemeral=True)
                         self.value = False
                         self.stop()
                         await interaction.response.defer()

                 view = RemoveConfigView(interaction)
                 await interaction.response.send_message(
                     f"A Muted role is already configured: {role.mention}.\nWould you like to **remove** this configuration instead?",
                     view=view,
                     ephemeral=True
                 )
                 await view.wait()

                 if view.value:
                     await config_manager.update_guild_config(interaction.guild_id, 'muted_role_id', None)
                     await interaction.edit_original_response(content=f"Configuration removed. {role.mention} is no longer the tracked Muted role.", view=None)
                     await log_audit(interaction.guild, f"{interaction.user.mention} removed Muted Role configuration.")
                 else:
                     await interaction.edit_original_response(content="Action cancelled.", view=None)
                 return
            else:
                 # Config exists but role is gone. Overwrite freely.
                 pass

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        try:
            # Create Role
            muted_role = await guild.create_role(name="Muted", reason="Bot Config: Create Muted Role")

            # Position Role
            # Attempt to place it below the bot's highest role
            try:
                # Find bot's top role
                bot_top_role = guild.me.top_role
                await muted_role.edit(position=bot_top_role.position - 1)
            except Exception as e:
                logger.error(f"Could not move role position: {e}")

            # Apply Overwrites to Channels
            perms = discord.PermissionOverwrite(send_messages=False, speak=False, add_reactions=False)

            count = 0
            for channel in guild.channels:
                try:
                    await channel.set_permissions(muted_role, overwrite=perms, reason="Bot Config: Apply Muted Role")
                    count += 1
                except:
                    pass

            # Save Config
            await config_manager.update_guild_config(guild.id, 'muted_role_id', muted_role.id)

            await interaction.followup.send(f"Created {muted_role.mention} and applied overwrites to {count} channels.", ephemeral=True)
            await log_audit(guild, f"{interaction.user.mention} created new Muted Role {muted_role.mention}.")

        except Exception as e:
            await interaction.followup.send(f"Failed to create muted role: {e}", ephemeral=True)

    @discord.app_commands.command(name="list", description="List current configuration")
    async def list_config(self, interaction: discord.Interaction):
        config = await config_manager.get_guild_config(interaction.guild_id)

        # Helper to format lists
        def fmt_channels(ids):
            return ", ".join([f"<#{c}>" for c in ids]) if ids else "None"

        def fmt_roles(ids):
            return ", ".join([f"<@&{r}>" for r in ids]) if ids else "None"

        embed = discord.Embed(title="Bot Configuration", color=discord.Color.blue())
        embed.add_field(name="Allowed Search Channels", value=fmt_channels(config.get('allowed_search_channels')), inline=False)

        fid = config.get('forum_channel_id')
        embed.add_field(name="Forum Channel", value=f"<#{fid}>" if fid else "Not Set", inline=False)

        lid = config.get('log_channel_id')
        embed.add_field(name="Log Channel", value=f"<#{lid}>" if lid else "Not Set", inline=False)

        embed.add_field(name="Moderator Roles", value=fmt_roles(config.get('mod_roles')), inline=False)

        mid = config.get('muted_role_id')
        embed.add_field(name="Muted Role", value=f"<@&{mid}>" if mid else "Not Set", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # No @app_commands here because we want a hybrid/text command logic
    @commands.command(name="sync", help="Force sync commands (Admin only)")
    async def sync_commands(self, ctx):
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("You need Administrator permissions.", delete_after=5)

        await ctx.send("Syncing commands...")
        try:
            # Sync to current guild
            self.bot.tree.copy_global_to(guild=ctx.guild)
            synced = await self.bot.tree.sync(guild=ctx.guild)
            await ctx.send(f"Synced {len(synced)} commands to this guild.")
        except Exception as e:
            await ctx.send(f"Failed to sync: {e}")

@bot.command(name="update", help="Pull latest code from GitHub and restart (Admin/Owner only)")
async def update_bot(ctx):
    # Check for admin
    if not ctx.author.guild_permissions.administrator:
        return await ctx.send("You need Administrator permissions.")

    await perform_update(ctx)

@bot.command(name="fix_duplicates", help="Fix duplicate commands by clearing guild commands (Admin/Owner only)")
async def fix_duplicates(ctx):
    # Check for admin
    if not ctx.author.guild_permissions.administrator:
        return await ctx.send("You need Administrator permissions.")

    await ctx.send("Attempting to fix duplicate commands (clearing guild-specific commands)...")
    try:
        # Clear commands for this guild
        bot.tree.clear_commands(guild=ctx.guild)
        await bot.tree.sync(guild=ctx.guild)

        # Resync global commands just in case?
        # Actually, if we clear guild commands, the global ones should show up
        # (assuming they are synced globally).
        # But if the global sync hasn't propagated, users might see nothing.
        # Let's trust setup_hook did global sync.

        await ctx.send("Guild commands cleared. Please restart your Discord client (Ctrl+R) to see changes. Only global commands should remain.")
    except Exception as e:
        await ctx.send(f"Error fixing duplicates: {e}")

# --- MODERATION COG ---
class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if await is_admin_or_mod(interaction):
            return True
        await interaction.response.send_message("You do not have permission to use moderation commands.", ephemeral=True)
        return False

    @discord.app_commands.command(name="kick", description="Kick a user from the server")
    async def kick(self, interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
        try:
            await user.kick(reason=reason)
            await interaction.response.send_message(f"Kicked {user.mention}. Reason: {reason}", ephemeral=True)
            await log_audit(interaction.guild, f"{interaction.user.mention} kicked {user.mention} (ID: {user.id}). Reason: {reason}", discord.Color.orange())
        except discord.Forbidden:
            await interaction.response.send_message("I do not have permission to kick this user.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Failed to kick user: {e}", ephemeral=True)

    @discord.app_commands.command(name="ban", description="Ban a user from the server")
    async def ban(self, interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
        try:
            await user.ban(reason=reason)
            await interaction.response.send_message(f"Banned {user.mention}. Reason: {reason}", ephemeral=True)
            await log_audit(interaction.guild, f"{interaction.user.mention} banned {user.mention} (ID: {user.id}). Reason: {reason}", discord.Color.red())
        except discord.Forbidden:
            await interaction.response.send_message("I do not have permission to ban this user.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Failed to ban user: {e}", ephemeral=True)

    @discord.app_commands.command(name="mute", description="Mute a user")
    async def mute(self, interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
        config = await config_manager.get_guild_config(interaction.guild_id)
        muted_role_id = config.get('muted_role_id')

        if not muted_role_id:
            await interaction.response.send_message("No Muted role configured. Use `/config set_muted_role` or `/config create_muted_role` first.", ephemeral=True)
            return

        role = interaction.guild.get_role(int(muted_role_id))
        if not role:
            await interaction.response.send_message("Configured Muted role not found in server.", ephemeral=True)
            return

        try:
            await user.add_roles(role, reason=reason)
            await interaction.response.send_message(f"Muted {user.mention}. Reason: {reason}", ephemeral=True)
            await log_audit(interaction.guild, f"{interaction.user.mention} muted {user.mention}. Reason: {reason}", discord.Color.yellow())
        except discord.Forbidden:
            await interaction.response.send_message("I do not have permission to assign the Muted role.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Failed to mute user: {e}", ephemeral=True)

    @discord.app_commands.command(name="unmute", description="Unmute a user")
    async def unmute(self, interaction: discord.Interaction, user: discord.Member):
        config = await config_manager.get_guild_config(interaction.guild_id)
        muted_role_id = config.get('muted_role_id')

        if not muted_role_id:
            await interaction.response.send_message("No Muted role configured.", ephemeral=True)
            return

        role = interaction.guild.get_role(int(muted_role_id))
        if not role:
            await interaction.response.send_message("Configured Muted role not found.", ephemeral=True)
            return

        try:
            if role in user.roles:
                await user.remove_roles(role, reason="Unmute command")
                await interaction.response.send_message(f"Unmuted {user.mention}.", ephemeral=True)
                await log_audit(interaction.guild, f"{interaction.user.mention} unmuted {user.mention}.", discord.Color.green())
            else:
                await interaction.response.send_message(f"{user.mention} is not muted.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I do not have permission to remove the Muted role.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Failed to unmute user: {e}", ephemeral=True)

# --- FUN COG ---
class Fun(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if await is_admin_or_mod(interaction):
            return True
        await interaction.response.send_message("You do not have permission to use fun commands.", ephemeral=True)
        return False

    @discord.app_commands.command(name="random_move", description="Randomly move a user between voice channels")
    @discord.app_commands.describe(user="The user to move", rounds="Number of moves (1-10, default 10)")
    async def random_move(self, interaction: discord.Interaction, user: discord.Member, rounds: int = 10):
        # Validate rounds
        if rounds < 1: rounds = 1
        if rounds > 10: rounds = 10

        if not user.voice or not user.voice.channel:
            await interaction.response.send_message(f"{user.mention} is not in a voice channel.", ephemeral=True)
            return

        # Get all voice channels in the guild
        voice_channels = interaction.guild.voice_channels
        if len(voice_channels) < 2:
            await interaction.response.send_message("Not enough voice channels to perform random moves.", ephemeral=True)
            return

        original_channel = user.voice.channel

        await interaction.response.send_message(f"Starting random move for {user.mention} ({rounds} times)...", ephemeral=True)
        await log_audit(interaction.guild, f"{interaction.user.mention} started random_move on {user.mention} ({rounds} times).", discord.Color.purple())

        try:
            for i in range(rounds):
                # Check if user is still connected
                if not user.voice:
                    break

                # Pick a random channel different from current
                current_channel = user.voice.channel
                available_channels = [c for c in voice_channels if c.id != current_channel.id]

                if not available_channels:
                    break

                target_channel = random.choice(available_channels)

                try:
                    await user.move_to(target_channel, reason="Random Move Fun Command")
                except discord.Forbidden:
                    await interaction.followup.send("I don't have permission to move this user.", ephemeral=True)
                    return
                except Exception:
                    pass # Ignore move errors

                await asyncio.sleep(1.5) # Sleep to avoid rate limits

            # Move back to original channel if possible
            if user.voice and original_channel:
                try:
                    await user.move_to(original_channel, reason="Returning to original channel")
                except:
                    pass

            await interaction.followup.send(f"Finished moving {user.mention}.", ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"Error during random move: {e}", ephemeral=True)

class GameSearch(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="search", description="Search for games on Online-Fix and FitGirl")
    @discord.app_commands.describe(query="The game to search for")
    async def search(self, ctx: commands.Context, *, query: str):
        logger.info(f"Received search command for '{query}' from {ctx.author}")

        # 1. Handle auto-deletion of request message (if prefix command)
        if not ctx.interaction:
            try:
                await ctx.message.delete()
            except discord.Forbidden:
                logger.warning("Missing permissions to delete user message.")
            except Exception as e:
                logger.error(f"Error deleting message: {e}")

        # Defer response
        if ctx.interaction:
            await ctx.defer(ephemeral=True)
        else:
            await ctx.typing()

        # Delegate to helper
        await perform_search(ctx, query, ctx.author)

from tracking import Tracking
from leveling import Leveling
from economy import Economy
from birthdays import Birthdays

async def setup_cogs():
    await bot.add_cog(ConfigGroup(bot))
    # Moderation is now part of Tracking/Advanced Mod, but old Moderation cog exists.
    # We should merge or replace. The new Tracking cog has 'warn' and 'tempmute'.
    # Old Moderation had 'kick', 'ban', 'mute', 'unmute'.
    # I will keep old Moderation for now, and Tracking adds the new ones.
    await bot.add_cog(Moderation(bot))
    await bot.add_cog(Fun(bot))
    await bot.add_cog(GameSearch(bot))

    await bot.add_cog(Tracking(bot))
    await bot.add_cog(Leveling(bot))
    await bot.add_cog(Economy(bot))
    await bot.add_cog(Birthdays(bot))

class HelpSelect(Select):
    def __init__(self, bot, ctx):
        self.bot = bot
        self.ctx = ctx
        options = [
            discord.SelectOption(label="Game Search", emoji="🎮", description="Search games and repacks"),
            discord.SelectOption(label="Moderation & Tracking", emoji="🛡️", description="Kick, Ban, Mute, Logs"),
            discord.SelectOption(label="Leveling", emoji="📈", description="Rank cards and XP"),
            discord.SelectOption(label="Economy", emoji="💰", description="Daily, Shop, Gambling"),
            discord.SelectOption(label="Fun & Misc", emoji="🎉", description="Random Move, Birthdays"),
            discord.SelectOption(label="Configuration", emoji="⚙️", description="Setup and Settings"),
        ]
        super().__init__(placeholder="Select a category...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        # Allow user to change selection, but response is ephemeral so others can't click anyway.
        # But if the menu persists (it does), we should check user.
        # Actually, since we're making it ephemeral, only the user sees it.
        # So this check is technically redundant for the interaction, but good practice.
        # Wait, if we edit the message, we can't make it ephemeral *after* the fact if it wasn't already.
        # The prompt asked for "not take the full view".
        # So the *initial* response should be ephemeral.

        val = self.values[0]
        embed = discord.Embed(title=f"{val} Commands", color=discord.Color.blue())

        cmds = []
        if val == "Game Search":
            cog = self.bot.get_cog("GameSearch")
            # Use get_commands() for standard Cogs with hybrid commands
            if cog: cmds = [c for c in cog.get_commands()]
        elif val == "Moderation & Tracking":
            # Combine Tracking (new mod) and Moderation (old mod)
            cog1 = self.bot.get_cog("Tracking")
            cog2 = self.bot.get_cog("Moderation")
            if cog1: cmds.extend([c for c in cog1.get_commands()])
            if cog2: cmds.extend([c for c in cog2.get_commands()])
        elif val == "Leveling":
            cog = self.bot.get_cog("Leveling")
            if cog: cmds = [c for c in cog.get_commands()]
        elif val == "Economy":
            cog = self.bot.get_cog("Economy")
            if cog: cmds = [c for c in cog.get_commands()]
        elif val == "Fun & Misc":
            cog1 = self.bot.get_cog("Fun")
            cog2 = self.bot.get_cog("Birthdays")
            if cog1: cmds.extend([c for c in cog1.get_commands()])
            if cog2: cmds.extend([c for c in cog2.get_commands()])
        elif val == "Configuration":
            cog = self.bot.get_cog("config")
            # Config is a GroupCog, so we use walk_app_commands
            if cog: cmds = [c for c in cog.walk_app_commands()]
            # Add manual commands
            embed.add_field(name="/setup", value="Run the interactive setup wizard.", inline=False)
            embed.add_field(name="@Bot update", value="Update the bot code.", inline=False)

        for cmd in cmds:
            desc = cmd.description if cmd.description else "No description"
            embed.add_field(name=f"/{cmd.name}", value=desc, inline=False)

        await interaction.response.edit_message(embed=embed, view=self.view)

class HelpView(View):
    def __init__(self, bot, ctx):
        super().__init__(timeout=120)
        self.add_item(HelpSelect(bot, ctx))

@bot.hybrid_command(name="help", description="Interactive command menu")
async def help_command(ctx: commands.Context):
    embed = discord.Embed(
        title="🤖 Calibre Bot Help",
        description="Select a category from the dropdown below to view commands.",
        color=discord.Color.brand_green()
    )
    view = HelpView(bot, ctx)

    if ctx.interaction:
        await ctx.interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    else:
        # Text command fallback (cannot be ephemeral)
        await ctx.send(embed=embed, view=view)

# Alias for backward compatibility
@bot.hybrid_command(name="showcommands", description="Alias for /help")
async def show_commands(ctx: commands.Context):
    await help_command(ctx)

@bot.hybrid_command(name="clear", description="Clear the last 10 messages (Owner Role only)")
@discord.app_commands.describe(amount="Number of messages to clear (default 10)")
async def clear(ctx: commands.Context, amount: int = 10):
    # Check permissions using helper
    # The helper handles Context vs Interaction internally now
    if not await is_admin_or_mod(ctx):
         await ctx.send("You do not have permission to use this command.", ephemeral=True)
         return

    # Delete the command message itself if possible
    if not ctx.interaction:
        try:
            await ctx.message.delete()
        except:
            pass

    # Perform purge
    try:
        deleted = await ctx.channel.purge(limit=amount)
        msg = await ctx.send(f"Deleted {len(deleted)} messages.", ephemeral=True)
        await log_audit(ctx.guild, f"{ctx.author.mention} cleared {len(deleted)} messages in {ctx.channel.mention}.")

        if not ctx.interaction:
            await asyncio.sleep(3)
            await msg.delete()

    except discord.Forbidden:
        await ctx.send("I do not have permission to manage messages.", ephemeral=True)
    except Exception as e:
        await ctx.send(f"Failed to clear messages: {e}", ephemeral=True)

    # Delete the command message itself if possible
    if not ctx.interaction:
        try:
            await ctx.message.delete()
        except:
            pass

    # Perform purge
    try:
        deleted = await ctx.channel.purge(limit=amount)
        msg = await ctx.send(f"Deleted {len(deleted)} messages.", ephemeral=True)
        await log_audit(ctx.guild, f"{ctx.author.mention} cleared {len(deleted)} messages in {ctx.channel.mention}.")

        if not ctx.interaction:
            await asyncio.sleep(3)
            await msg.delete()

    except discord.Forbidden:
        await ctx.send("I do not have permission to manage messages.", ephemeral=True)
    except Exception as e:
        await ctx.send(f"Failed to clear messages: {e}", ephemeral=True)

@bot.event
async def on_command(ctx):
    logger.info(f"Text Command '{ctx.command}' invoked by {ctx.author} in {ctx.guild if ctx.guild else 'DM'}")

@bot.event
async def on_app_command_completion(interaction, command):
    logger.info(f"Slash Command '{command.name}' invoked by {interaction.user} in {interaction.guild if interaction.guild else 'DM'}")

# Main Execution
if __name__ == "__main__":
    if not TOKEN:
        logger.error("Error: DISCORD_TOKEN not found in .env")
    else:
        # Register Cogs on startup
        async def main():
            await setup_cogs()
            await bot.start(TOKEN)

        asyncio.run(main())
