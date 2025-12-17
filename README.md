# CALIBRE SEARCH BOT v2.0

A Discord bot for searching game repacks (FitGirl, Online-Fix), managing server configurations, and basic moderation.

## Features

- **Game Search:** Search FitGirl Repacks and Online-Fix for games.
- **Thread Scanning:** Automatically checks for existing threads to prevent duplicates.
- **Configuration System:** Interactive setup and granular configuration for roles and channels.
- **Moderation:** Kick, Ban, Mute, Unmute.
- **Fun:** Random Move command.

## Setup

1. **Install Requirements:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Environment Variables:**
   Create a `.env` file:
   ```env
   DISCORD_TOKEN=your_token_here
   ```

3. **Run the Bot:**
   ```bash
   python bot.py
   ```

4. **Initial Configuration:**
   Run the interactive setup wizard in your server (requires Server Owner):
   ```
   /setup
   ```

## Commands

### Game Search
- `/search <query>`: Search for a game. If a thread exists, it will link you to it.

### Configuration (Admin/Mod)
- `/setup`: Run the interactive setup wizard (Server Owner Only).
- `/config allow <channel>`: Allow searching in a text channel.
- `/config deny <channel>`: Disallow searching in a text channel.
- `/config forum <channel>`: Set the forum channel for game threads.
- `/config logs <channel>`: Set the log channel.
- `/config add_mod <role>`: Add a moderator role.
- `/config remove_mod <role>`: Remove a moderator role.
- `/config muted_role <role>`: Set the Muted role.
- `/config create_mute`: Create a Muted role with channel overwrites.
- `/config list`: List current configuration.

### Moderation
- `/kick <user>`
- `/ban <user>`
- `/mute <user>`
- `/unmute <user>`
- `/clear <amount>`: Clear messages.

### Fun
- `/random_move <user> <rounds>`: Move a user between voice channels.

### Troubleshooting
- `!fix_duplicates`: Run this text command if you see duplicate slash commands (e.g., two `/ban` commands). It clears guild-specific commands.
- `!sync`: Force sync commands to the current guild.
