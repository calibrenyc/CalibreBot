import os
import discord
from discord.ext import commands
from discord.ui import Select, View
from dotenv import load_dotenv
import scrapers
import asyncio
from config_manager import config_manager

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
# Global env vars are now deprecated in favor of guild config,
# but we keep OWNER_ROLE_ID as a fallback or for global admin commands.
OWNER_ROLE_ID = os.getenv('OWNER_ROLE_ID')

# Setup Bot
class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        # Prefix '!' allows !search to work alongside /search
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # Sync slash commands globally
        await self.tree.sync()
        print("Commands synced.")

bot = MyBot()

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
            
            # --- Get Configured Destination Channel ---
            guild_id = interaction.guild_id
            config = config_manager.get_guild_config(guild_id)
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
                            print(f"Could not fetch FORUM_CHANNEL_ID {forum_channel_id}")
                except ValueError:
                    print(f"Invalid FORUM_CHANNEL_ID: {forum_channel_id}")
            
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
                    if t.name == selected_result['title']:
                        existing_thread = t
                        break

            # 2. Check archived threads (if not found in active)
            if not existing_thread and hasattr(destination_channel, 'archived_threads'):
                async for t in destination_channel.archived_threads(limit=None):
                    if t.name == selected_result['title']:
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
            print(f"Creating thread for '{selected_result['title']}' in {destination_channel.name} ({destination_channel.type})...")
            
            thread = None
            message_content = f"{self.original_user.mention} Here is the link you requested:\n{selected_result['link']}"

            if isinstance(destination_channel, discord.ForumChannel):
                # Forum Channel creation
                thread_with_message = await destination_channel.create_thread(
                    name=selected_result['title'],
                    content=message_content
                )
                thread = thread_with_message.thread
            
            elif isinstance(destination_channel, discord.TextChannel):
                # Text Channel creation
                thread = await destination_channel.create_thread(
                    name=selected_result['title'],
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
            print(f"Error in callback: {e}")
            try:
                await interaction.followup.send(f"Failed to create thread: {e}", ephemeral=True)
            except:
                pass

class SearchView(View):
    def __init__(self, results, original_user):
        super().__init__()
        self.add_item(SearchResultSelect(results, original_user))

# Helper to check permissions
def is_admin_or_mod(obj):
    """
    Checks if the user executing the command (Context or Interaction) is an Admin or Mod.
    obj: can be discord.Interaction or commands.Context
    """
    user = obj.author if isinstance(obj, commands.Context) else obj.user
    guild = obj.guild

    if not guild:
        return False # No permissions in DMs usually

    # Check Administrator Permission
    # For Context, permissions are in channel_permissions or guild_permissions
    if isinstance(obj, commands.Context):
        if obj.author.guild_permissions.administrator:
            return True
    else:
        # Interaction
        if obj.permissions.administrator:
            return True

    # Check Configured Mod Roles
    config = config_manager.get_guild_config(guild.id)
    mod_roles = config.get('mod_roles', [])

    if mod_roles:
        for role in user.roles:
            if role.id in mod_roles:
                return True

    # Fallback to OWNER_ROLE_ID if set (legacy support)
    if OWNER_ROLE_ID:
        try:
            if any(r.id == int(OWNER_ROLE_ID) for r in user.roles):
                return True
        except:
            pass

    return False

async def log_error(guild, message):
    if not guild: return
    config = config_manager.get_guild_config(guild.id)
    log_channel_id = config.get('log_channel_id')
    if log_channel_id:
        try:
            channel = guild.get_channel(int(log_channel_id))
            if channel:
                await channel.send(f"[Error] {message}")
        except Exception as e:
            print(f"Failed to log error to channel {log_channel_id}: {e}")

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
        config = config_manager.get_guild_config(guild_id)
        allowed_channels = config.get('allowed_search_channels', [])

        current_channel_id = interaction_or_ctx.channel.id

        # Rule: If allowed list is NOT empty, strict enforcement.
        # If allowed list IS empty, should we allow?
        # Requirement 3 implies "if no configured channel is set... not post anywhere".
        # So if list is empty, default to BLOCK (unless Admin setup needed?)
        # Let's say if list is empty, BLOCK.

        if not allowed_channels:
             # Check if we should warn
             if is_admin_or_mod(interaction_or_ctx if not is_ctx else interaction_or_ctx.message):
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

    print(f"Performing search for '{query}'...")

    try:
        # Run scrapers
        # Note: We need 'bot' here. Since this is outside class, we use the global 'bot' instance.
        online_fix_results = await bot.loop.run_in_executor(None, scrapers.search_online_fix, query)
        fitgirl_results = await bot.loop.run_in_executor(None, scrapers.search_fitgirl, query)

        all_results = online_fix_results + fitgirl_results
        print(f"Total results found: {len(all_results)}")

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

        print("Response sent to user.")

    except Exception as e:
        print(f"Error during search: {e}")
        await send_msg(f"An error occurred while searching: {e}")

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')

# --- SETUP COMMAND ---
@bot.hybrid_command(name="setup", description="Auto-configure the bot for this server (Admin only)")
async def setup(ctx: commands.Context):
    # Check Admin
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("You need Administrator permissions to run this command.", ephemeral=True)
        return

    view = YesNoView(ctx)
    msg = await ctx.send("Do you want to automatically create a 'game-requests' channel, a 'bot-logs' channel, and a 'Game Threads' forum channel?", view=view)

    await view.wait()

    if view.value is None:
        await ctx.send("Timed out.", ephemeral=True)
    elif view.value:
        # User said YES
        guild = ctx.guild
        try:
            # Create Category
            category = await guild.create_category("Game Bot")

            # Create Text Channels
            req_channel = await guild.create_text_channel("game-requests", category=category)
            log_channel = await guild.create_text_channel("bot-logs", category=category)

            # Create Forum Channel
            forum_channel = await guild.create_forum_channel("Game Threads", category=category)

            # Save Config
            config_manager.update_guild_config(guild.id, 'forum_channel_id', forum_channel.id)
            config_manager.update_guild_config(guild.id, 'log_channel_id', log_channel.id)
            config_manager.add_to_list(guild.id, 'allowed_search_channels', req_channel.id)

            await ctx.send(f"Setup complete!\nRequest Channel: {req_channel.mention}\nLog Channel: {log_channel.mention}\nForum: {forum_channel.mention}\n\nThe bot is now allowed to search in {req_channel.mention}.", ephemeral=True)

        except Exception as e:
            await ctx.send(f"Error during setup: {e}", ephemeral=True)
    else:
        # User said NO
        await ctx.send("Automatic setup cancelled. Please use `/config` commands to configure manually.", ephemeral=True)

# --- CONFIG GROUP ---
class ConfigGroup(commands.GroupCog, name="config"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if is_admin_or_mod(interaction):
            return True
        await interaction.response.send_message("You do not have permission to use config commands.", ephemeral=True)
        return False

    @discord.app_commands.command(name="allow_channel", description="Allow searching in a text channel")
    async def allow_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        config_manager.add_to_list(interaction.guild_id, 'allowed_search_channels', channel.id)
        await interaction.response.send_message(f"Added {channel.mention} to allowed search channels.", ephemeral=True)

    @discord.app_commands.command(name="disallow_channel", description="Disallow searching in a text channel")
    async def disallow_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        config_manager.remove_from_list(interaction.guild_id, 'allowed_search_channels', channel.id)
        await interaction.response.send_message(f"Removed {channel.mention} from allowed search channels.", ephemeral=True)

    @discord.app_commands.command(name="set_forum", description="Set the forum channel for game threads")
    async def set_forum(self, interaction: discord.Interaction, channel: discord.ForumChannel):
        config_manager.update_guild_config(interaction.guild_id, 'forum_channel_id', channel.id)
        await interaction.response.send_message(f"Forum channel set to {channel.mention}.", ephemeral=True)

    @discord.app_commands.command(name="set_logs", description="Set the log channel for bot errors")
    async def set_logs(self, interaction: discord.Interaction, channel: discord.TextChannel):
        config_manager.update_guild_config(interaction.guild_id, 'log_channel_id', channel.id)
        await interaction.response.send_message(f"Log channel set to {channel.mention}.", ephemeral=True)

    @discord.app_commands.command(name="add_mod_role", description="Add a role that can manage bot config")
    async def add_mod_role(self, interaction: discord.Interaction, role: discord.Role):
        config_manager.add_to_list(interaction.guild_id, 'mod_roles', role.id)
        await interaction.response.send_message(f"Added {role.mention} as a moderator role.", ephemeral=True)

    @discord.app_commands.command(name="list", description="List current configuration")
    async def list_config(self, interaction: discord.Interaction):
        config = config_manager.get_guild_config(interaction.guild_id)

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

        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup_cogs():
    await bot.add_cog(ConfigGroup(bot))

@bot.hybrid_command(name="search", description="Search for games on Online-Fix and FitGirl")
@discord.app_commands.describe(query="The game to search for")
async def search(ctx: commands.Context, *, query: str):
    print(f"Received search command for '{query}' from {ctx.author}")

    # 1. Handle auto-deletion of request message (if prefix command)
    if not ctx.interaction:
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            print("Missing permissions to delete user message.")
        except Exception as e:
            print(f"Error deleting message: {e}")

    # Defer response
    if ctx.interaction:
        await ctx.defer(ephemeral=True)
    else:
        await ctx.typing()

    # Delegate to helper
    await perform_search(ctx, query, ctx.author)

@bot.hybrid_command(name="clear", description="Clear the last 10 messages (Owner Role only)")
@discord.app_commands.describe(amount="Number of messages to clear (default 10)")
async def clear(ctx: commands.Context, amount: int = 10):
    # Check permissions using helper
    if not is_admin_or_mod(ctx if hasattr(ctx, 'permissions') else ctx.interaction): # Hacky context check
         # Actually just check manually since clear might be strict owner
         pass

    # Use old OWNER check for clear command specifically as requested in original prompt?
    # User said "other commands should be allowed anywhere. And yes, there should be a permission for not only owner, but moderators"
    # So clear should check is_admin_or_mod.

    if not is_admin_or_mod(ctx.interaction if ctx.interaction else ctx): # ctx matches interaction interface mostly
         # Wait, context doesn't have permissions attribute the same way always.
         # Let's use the helper properly.
         # Actually, for hybrid commands, ctx is Context.
         # Helper takes interaction.
         # Let's rebuild permission check inline for context.
         is_auth = False
         if ctx.author.guild_permissions.administrator: is_auth = True
         if not is_auth:
             config = config_manager.get_guild_config(ctx.guild.id)
             for r in ctx.author.roles:
                 if r.id in config.get('mod_roles', []):
                     is_auth = True
                     break
         if not is_auth and OWNER_ROLE_ID: # Legacy
             # Simplified check
             pass

         if not is_auth:
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
        
        if not ctx.interaction:
            await asyncio.sleep(3)
            await msg.delete()
            
    except discord.Forbidden:
        await ctx.send("I do not have permission to manage messages.", ephemeral=True)
    except Exception as e:
        await ctx.send(f"Failed to clear messages: {e}", ephemeral=True)

# Main Execution
if __name__ == "__main__":
    if not TOKEN:
        print("Error: DISCORD_TOKEN not found in .env")
    else:
        # Register Cogs on startup
        async def main():
            await setup_cogs()
            await bot.start(TOKEN)

        asyncio.run(main())
