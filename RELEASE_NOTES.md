# Calibre Search Bot - Version 2.0 Release Notes

We are excited to announce the release of **Calibre Search Bot v2.0**! This major update brings a complete overhaul of the configuration system, a smarter thread management engine, and new moderation tools.

## 🌟 New Features

### 🧵 Smart Thread Scanning
*   **Prevent Duplicates:** The bot now intelligently scans both *active* and *archived* threads in your forum channel before creating a new one.
*   **Interactive Prompt:** If a thread with the same game title exists, the bot will ask if you want to be linked to that thread instead of cluttering the channel with a duplicate.
*   **Discord API Compliance:** Game titles are automatically truncated to 100 characters to prevent errors and ensure consistent matching with Discord thread names.

### 🔍 Enhanced Search Engine
*   **New Providers:** We have switched our search providers to **FitGirl Repacks** (via `cloudscraper` for bot protection bypass) and **Online-Fix**.
*   **Strict Filtering:** Results are prioritized. Exact title matches appear first. If none are found, "Similar Titles" are displayed.
*   **Retry Option:** The search dropdown now includes a "None of the options above" button, allowing you to instantly retry with a refined query.
*   **Dedicated Category:** The `/search` command now lives in its own "Game Search" category in the help menu.

### ⚙️ Robust Configuration System
*   **Per-Guild Config:** All settings (channels, roles, logs) are now saved per-guild in `guild_configs.json`.
*   **Interactive Wizard:** Run `/setup` for a guided, step-by-step installation (Restricted to **Server Owner only**).
*   **Simplified Commands:** We've streamlined the command names for better usability:
    *   `/config add_mod` / `/config remove_mod`
    *   `/config allow` / `/config deny` (for channel permissions)
    *   `/config forum` / `/config logs`
    *   `/config muted_role` / `/config create_mute`
*   **Smart Mute Setup:** `/config create_mute` now checks if a role is already configured and offers to remove the existing configuration safely.

### 🛡️ Moderation & Fun
*   **New Moderation Cog:** Built-in commands for `/kick`, `/ban`, `/mute`, and `/unmute`.
*   **Audit Logging:** Critical actions (setup, config changes, mod actions) are logged to your configured log channel with timestamps and user info.
*   **Fun Commands:** Added `/random_move` to randomly move a user between voice channels (great for trolling friends!).

## 🐛 Bug Fixes & Improvements

*   **Duplicate Commands Fix:** Added a text-based `!fix_duplicates` command (Admin only) to clear guild-specific slash commands, resolving the issue where commands appeared twice.
*   **Command Sync:** Added `!sync` to force-register slash commands if they don't appear immediately.
*   **Stability:** Fixed issues with long thread titles crashing the bot.
*   **Cleanliness:** Interaction messages (prompts, confirmations) are now auto-deleted to keep your channels clean.

## 📋 How to Update

1.  **Pull the latest code.**
2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
3.  **Run the bot:**
    ```bash
    python bot.py
    ```
4.  **Run Setup (if new):**
    ```
    /setup
    ```
5.  **Fix Duplicates (if updating):**
    Run `!fix_duplicates` in your server to clean up old command registrations.
