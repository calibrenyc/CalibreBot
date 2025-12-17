# MaybeCalibre Bot

A feature-rich Discord bot designed to search for games on **Online-Fix.me** and **FitGirl Repacks**, manage server configurations, and provide moderation tools.

## Features

### Game Search & Management
- **/search <query>**: Searches **Online-Fix.me** and **FitGirl Repacks** for games.
- **Smart Thread Scanning**: Before creating a new thread, the bot scans specifically for existing threads (active or archived) matching the exact game title to prevent duplicates.
- **Interactive Results**: Presents a dropdown menu. Includes a "None of the options above" choice to refine the search.
- **Thread Creation**: Automatically creates a forum post with the game title and links inside the configured Forum Channel.

### Configuration System
- **Per-Server Config**: settings are stored per guild.
- **/setup**: An interactive wizard to initialize the bot on a new server.
    - Sets Owner and Moderator roles.
    - Automatically creates 'game-requests', 'Game Threads', and private 'bot-logs' channels.
- **/config**: Granular commands to manage settings manually (`allow_channel`, `set_forum`, `set_logs`, `add_mod_role`, etc.).

### Moderation Suite
- **Commands**: `/kick`, `/ban`, `/mute`, `/unmute`.
- **Muted Role**: Automated creation and management of a "Muted" role that denies speaking/typing permissions across all channels.
- **Audit Logging**: All moderation and configuration actions are logged to the configured log channel.

### Fun Commands
- **/random_move <user> [rounds]**: Randomly moves a user between voice channels for a specified number of rounds (1-10) and returns them to their original channel.

## Setup

1.  **Install Python**: Ensure you have Python 3.8+ installed.
2.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
3.  **Configure Environment**:
    - Rename `.env.example` to `.env`.
    - Open `.env` and paste your Discord Bot Token:
      ```
      DISCORD_TOKEN=your_token_here
      ```
    - Note: Channel IDs are no longer required in `.env`; use `/setup` inside Discord.

## How to Run

### Windows
Double-click `start.bat`.

### Linux / macOS
Run the following in your terminal:
```bash
./start.sh
```

## Requirements
- `discord.py`
- `cloudscraper`
- `beautifulsoup4`
- `python-dotenv`
- `requests`
