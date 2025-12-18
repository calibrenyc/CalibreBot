# CALIBRE SEARCH BOT v2.1.0

A Discord bot for searching game repacks (FitGirl, Online-Fix), managing server configurations, and advanced features like economy, leveling, and moderation.

## Features

### 🎮 Game Search
- **Providers:** FitGirl Repacks, Online-Fix.
- **Smart Search:** Prevents duplicate threads by scanning for existing ones.
- **Commands:** `/search <query>`, `@CalibreBot search <query>`.

### 🛡️ Moderation & Tracking
- **Logging:** Voice join/leave durations, kicks, and flagged words logged to `bot-logs`.
- **Commands:**
    - `/warn <user> <reason>`: Warn a user and log it.
    - `/tempmute <user> <duration>`: Timeout a user.
    - `/modlogs <user>`: View warning history.
    - `/kick`, `/ban`, `/mute`, `/unmute`.

### 📈 Leveling System
- **XP:** Earn XP from messaging and voice chat activity.
- **Rank Card:** `/rank` displays a custom profile card with your level and progress.
- **Customization:** `/rank settings background <url>`, `/rank settings color <hex>`.

### 💰 Economy System
- **Global Currency:** Users keep their balance across servers.
- **Commands:**
    - `/daily`: Claim daily coins.
    - `/balance`: Check your wallet.
    - `/gamble rps <amount> <choice>`: Play Rock-Paper-Scissors.
    - `/shop list`: View items/roles for sale in the server.
    - `/shop buy <item>`: Buy items.
    - `/bet`: Create and place custom bets on events.

### 🎂 Birthdays
- `/birthday set DD/MM`: Set your birthday.
- **Notifications:** Daily announcements in the general/log channel.

### ⚙️ Configuration
- **Setup Wizard:** `/setup` (Server Owner only).
- **Settings:** `/config <allow/deny/forum/logs/add_mod...>`
- **Auto-Update:** `@CalibreBot update` (Admin only) - Supports private repos via `.env`.

## Setup

1. **Install Requirements:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Environment Variables (.env):**
   ```env
   DISCORD_TOKEN=your_token
   GITHUB_TOKEN=your_pat_token # Optional: For auto-updating from private repos
   ```

3. **Run:**
   ```bash
   python bot.py
   ```

## Troubleshooting
- **Updates:** If auto-update fails on a private repo, ensure `GITHUB_TOKEN` is set in `.env` or use `GIT_REPO_URL`.
- **Database:** Data is stored in `bot_data.db`. Do not delete this file unless you want to reset everything.
