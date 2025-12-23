# Calibre Search Bot - Version 2.5 Release Notes

**Version 2.5 (Operation Health)** focuses on cleaning up technical debt, fixing bugs, and revamping core systems for better stability and user experience.

## 🏥 Operation Health Updates

### ⚔️ Economy & PvP Wagers
*   **Revamped Betting:** Replaced the old betting system with a robust **PvP Wager System** (`/wager`).
    *   **Challenge:** `/wager challenge <user> <amount>` - Funds are securely escrowed.
    *   **Secure:** Opponents must Accept/Decline via buttons.
    *   **Resolution:** Both players vote on the winner (`/wager resolve`). If votes mismatch, the bet is voided and funds returned.

### 🎰 Casino Improvements
*   **Lucky Charm Integration:** If you own a 'Lucky Charm' (from `/shop`), the Slot Machine (`/slots`) will now offer a special **"Spin with Luck"** button to consume the item for boosted odds!
*   **RTP Persistence:** The `set_rtp` command for Admins is now persistent across bot restarts (saved to DB).

### 📈 Leveling & Config
*   **Rank Reset:** Admins can now reset XP for a specific user or the entire server using `/leveling reset`.
*   **Level Up Channel:** You can now configure a specific channel for level-up notifications using `/config level_channel`, keeping general chat clean.

### 🧹 System Cleanup
*   **Log Files:** Removed clutter from local `.log` files; logging is now streamlined to console.
*   **Database:** Optimized schema with new `global_config` and `pvp_bets` tables.

---

# Calibre Search Bot - Version 2.1.0 Release Notes

**Version 2.1.0** is a massive update introducing persistent storage (SQLite), an economy system, leveling, advanced tracking, and birthdays!

## 🌟 New Features

### 💾 Persistent Database (SQLite)
*   Moved from JSON to a robust SQLite database (`bot_data.db`).
*   **Migration:** Automatically migrates your existing `guild_configs.json` on startup.

### 🛡️ Activity Tracking & Moderation
*   **Voice Logging:** Logs when users join/leave voice channels and calculates the duration of their session.
*   **Kick Detection:** Detects if a member was kicked (via Audit Logs) and logs the moderator responsible.
*   **Flagged Words:** Logs usage of blacklisted words to the bot-log channel.
*   **New Commands:**
    *   `/warn <user> <reason>`: Issues a warning and tracks it in the database.
    *   `/modlogs <user>`: View a user's warning history.
    *   `/tempmute <user> <duration>`: Uses Discord's native Timeout feature.

### 📈 Leveling System
*   **XP Sources:** Earn XP by chatting and spending time in voice channels.
*   **Rank Card:** `/rank` generates a beautiful image card showing your avatar, level, and progress bar.
*   **Customization:** Users can set their own card background (`/rank settings background`) and accent color.

### 💰 Global Economy & Shop
*   **Global Balance:** Your coin balance follows you across all servers using this bot.
*   **Daily Rewards:** `/daily` gives coins once every 24 hours.
*   **Gambling:** `/gamble rps` (Rock Paper Scissors) to double your money (or lose it!).
*   **Server Shop:** Admins can create items (`/shop add`) that award Roles when bought (`/shop buy`).
*   **Betting System:** Create custom bets (`/bet create`) for server events, let users place bets (`/bet place`), and resolve them to distribute the pot (`/bet resolve`).

### 🎂 Birthdays
*   **Set Birthday:** `/birthday set DD/MM`.
*   **Announcements:** The bot automatically wishes users a Happy Birthday in the server.

## 🛠️ Improvements
*   **Rich Embeds:** All logs and command responses now use formatted Embeds for a cleaner look.
*   **Async Logic:** The entire configuration system was rewritten to be asynchronous for better performance.

## 📋 Update Instructions
1.  Pull the latest code.
2.  Install new dependencies: `pip install -r requirements.txt` (Adds `Pillow` and `aiosqlite`).
3.  Restart the bot. It will automatically migrate your config.
