import os
import discord
from discord.ext import commands
from discord.ui import Select, View
from dotenv import load_dotenv
import scrapers
import asyncio

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
TARGET_CHANNEL_ID = os.getenv('TARGET_CHANNEL_ID') # Optional: ID of channel where commands are allowed
FORUM_CHANNEL_ID = os.getenv('FORUM_CHANNEL_ID') # ID of the Forum/Text channel where threads are created
OWNER_ROLE_ID = os.getenv('OWNER_ROLE_ID') # ID of the role allowed to use admin commands

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
            # Confirm to user
            await interaction.response.edit_message(content=f"Posted in {self.thread.mention}.", view=None)
        except Exception as e:
            await interaction.response.edit_message(content=f"Failed to post in thread: {e}", view=None)

    @discord.ui.button(label="No", style=discord.ButtonStyle.red)
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Okay, please try searching again with a different query.", view=None)

class SearchResultSelect(Select):
    def __init__(self, results, original_interaction_user):
        # Limit to 25 options (Discord limit)
        options = []
        for i, res in enumerate(results[:25]):
            # Truncate title if too long
            label = res['title'][:95] + "..." if len(res['title']) > 95 else res['title']
            description = f"Source: {res['source']}"
            options.append(discord.SelectOption(
                label=label, 
                description=description, 
                value=str(i)
            ))
        
        super().__init__(placeholder="Select a game to create a thread...", min_values=1, max_values=1, options=options)
        self.results = results
        self.original_user = original_interaction_user

    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
            selected_index = int(self.values[0])
            selected_result = self.results[selected_index]
            
            # Determine destination channel (Forum Channel)
            destination_channel = None
            
            if FORUM_CHANNEL_ID:
                try:
                    fetched_channel = bot.get_channel(int(FORUM_CHANNEL_ID))
                    if fetched_channel:
                        destination_channel = fetched_channel
                    else:
                        # Attempt to fetch if not in cache
                        try:
                            fetched_channel = await bot.fetch_channel(int(FORUM_CHANNEL_ID))
                            destination_channel = fetched_channel
                        except:
                            print(f"Could not fetch FORUM_CHANNEL_ID {FORUM_CHANNEL_ID}")
                except ValueError:
                    print(f"Invalid FORUM_CHANNEL_ID: {FORUM_CHANNEL_ID}")
            
            # If no forum channel configured, fallback to current channel (or error if strictly required)
            if not destination_channel:
                 destination_channel = interaction.channel

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
                await interaction.followup.edit_message(
                    message_id=interaction.message.id,
                    content=f"A thread for '{selected_result['title']}' already exists: {existing_thread.mention}.\nIs this the game you are looking for?",
                    view=view
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

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')

@bot.hybrid_command(name="search", description="Search for games on Online-Fix and CS.RIN.RU")
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
    
    try:
        # Run scrapers
        print("Starting scrapers...")
        online_fix_results = await bot.loop.run_in_executor(None, scrapers.search_online_fix, query)
        cs_rin_results = await bot.loop.run_in_executor(None, scrapers.search_cs_rin, query)
        
        all_results = online_fix_results + cs_rin_results
        print(f"Total results found: {len(all_results)}")
        
        if not all_results:
            msg = f"No results found for '{query}'."
            if ctx.interaction:
                await ctx.send(msg, ephemeral=True)
            else:
                # Send ephemeral-like message by deleting it after delay
                sent_msg = await ctx.send(msg)
                await asyncio.sleep(5)
                await sent_msg.delete()
            return
            
        # Pass ctx.author so we know who to tag in the thread
        view = SearchView(all_results, ctx.author)
        msg = f"Found {len(all_results)} results for '{query}':"
        
        if ctx.interaction:
            await ctx.send(msg, view=view, ephemeral=True)
        else:
            await ctx.send(msg, view=view)
            
        print("Response sent to user.")
        
    except Exception as e:
        print(f"Error during search: {e}")
        error_msg = f"An error occurred while searching: {e}"
        if ctx.interaction:
            await ctx.send(error_msg, ephemeral=True)
        else:
            await ctx.send(error_msg)

@bot.hybrid_command(name="clear", description="Clear the last 10 messages (Owner Role only)")
@discord.app_commands.describe(amount="Number of messages to clear (default 10)")
async def clear(ctx: commands.Context, amount: int = 10):
    # Check if user has the allowed role
    if not OWNER_ROLE_ID:
        await ctx.send("OWNER_ROLE_ID is not configured.", ephemeral=True)
        return

    has_role = False
    try:
        required_role_id = int(OWNER_ROLE_ID)
        if any(role.id == required_role_id for role in ctx.author.roles):
            has_role = True
    except ValueError:
        pass # Invalid ID format
    except AttributeError:
        pass # DM context or user has no roles

    if not has_role:
        await ctx.send("You do not have permission to use this command.", ephemeral=True)
        return

    # Delete the command message itself if possible (for clean logs), 
    # though purge might catch it if it's not ephemeral.
    if not ctx.interaction:
        try:
            await ctx.message.delete()
        except:
            pass
            
    # Perform purge
    try:
        deleted = await ctx.channel.purge(limit=amount)
        msg = await ctx.send(f"Deleted {len(deleted)} messages.", ephemeral=True)
        
        # If not ephemeral (text context), delete confirmation after 3s
        if not ctx.interaction:
            await asyncio.sleep(3)
            await msg.delete()
            
    except discord.Forbidden:
        await ctx.send("I do not have permission to manage messages.", ephemeral=True)
    except Exception as e:
        await ctx.send(f"Failed to clear messages: {e}", ephemeral=True)

if __name__ == "__main__":
    if not TOKEN:
        print("Error: DISCORD_TOKEN not found in .env")
    else:
        bot.run(TOKEN)
