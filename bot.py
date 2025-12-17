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

async def perform_search(interaction_or_ctx, query, user):
    """
    Shared search logic to be used by the command and the retry flow.
    interaction_or_ctx: can be Context (from command) or Interaction (from retry)
    """
    # Helper to send messages appropriately
    async def send_msg(content, view=None, ephemeral=True):
        if isinstance(interaction_or_ctx, commands.Context):
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
