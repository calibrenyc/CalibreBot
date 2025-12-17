# Discord Game Search Bot

A Discord bot that allows users to search for games on **Online-Fix.me** and **CS.RIN.RU** directly from Discord. It uses slash commands to fetch results and creates a dedicated thread with the game link upon selection.

## Features

- **/search <query>**: Searches both websites for the game. Supports both slash commands and prefix commands (`!search`).
- **Interactive Results**: Presents a dropdown menu of found games.
- **Thread Creation**: Automatically creates a public thread (or forum post) with the game title and posts the download/forum link inside.
- **User Notification**: Tags the user who requested the game inside the new thread.
- **Bypass Protections**: Uses `cloudscraper` and `ddgs` (DuckDuckGo Search) to handle bot protections.

## Setup

1.  **Install Python**: Ensure you have Python 3.8+ installed.
2.  **Configure Environment**:
    - Rename `.env.example` to `.env`.
    - Open `.env` and paste your Discord Bot Token:
      ```
      DISCORD_TOKEN=your_token_here
      FORUM_CHANNEL_ID=your_forum_channel_id
      ```
    - `FORUM_CHANNEL_ID`: The ID of the Forum Channel (or Text Channel) where the bot should create threads.
    - `TARGET_CHANNEL_ID`: (Optional) ID of a specific channel.

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
- `ddgs`
