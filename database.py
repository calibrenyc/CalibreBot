import aiosqlite
import json
import os
import asyncio

DB_FILE = "bot_data.db"

class DatabaseManager:
    def __init__(self):
        self.db_file = DB_FILE

    async def init_db(self):
        async with aiosqlite.connect(self.db_file) as db:
            # 1. Guild Configs (Replaces JSON)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS guild_configs (
                    guild_id INTEGER PRIMARY KEY,
                    owner_role_id INTEGER,
                    forum_channel_id INTEGER,
                    log_channel_id INTEGER,
                    muted_role_id INTEGER,
                    allowed_search_channels TEXT, -- JSON List
                    mod_roles TEXT -- JSON List
                )
            """)

            # 2. Flagged Words (Per Guild)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS flagged_words (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    word TEXT,
                    UNIQUE(guild_id, word)
                )
            """)

            # 3. Warnings (Moderation)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS warnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    user_id INTEGER,
                    moderator_id INTEGER,
                    reason TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 4. Leveling (Per Guild)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_levels (
                    guild_id INTEGER,
                    user_id INTEGER,
                    xp INTEGER DEFAULT 0,
                    level INTEGER DEFAULT 0,
                    last_message_time REAL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)

            # 5. Global Economy / Profile (Global)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS global_users (
                    user_id INTEGER PRIMARY KEY,
                    balance INTEGER DEFAULT 0,
                    last_daily REAL DEFAULT 0,
                    bg_url TEXT DEFAULT NULL,
                    card_color TEXT DEFAULT '#7289da'
                )
            """)

            # 6. Shop Items (Per Guild? Or Global? Prompt says "create your own currency... items... in your Discord server".
            # Implies per-server items (paid roles are definitely per server).
            # But currency is global.
            # Let's make Shop Items Per Guild.
            await db.execute("""
                CREATE TABLE IF NOT EXISTS shop_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    name TEXT,
                    price INTEGER,
                    role_id INTEGER,
                    description TEXT
                )
            """)

            # 7. Inventory (Global? Or Per Server? If items are roles, inventory is just "instant use" usually).
            # If items are roles, we don't store them in inventory, we just give the role.
            # But "items" could be other things. For now, we'll implement simple role-buy system.

            # 8. Active Bets (Per Guild)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS active_bets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    description TEXT,
                    options TEXT, -- JSON list of options
                    status TEXT DEFAULT 'OPEN', -- OPEN, CLOSED, RESOLVED
                    creator_id INTEGER,
                    winning_option TEXT DEFAULT NULL
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS bet_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bet_id INTEGER,
                    user_id INTEGER,
                    option TEXT,
                    amount INTEGER,
                    FOREIGN KEY(bet_id) REFERENCES active_bets(id)
                )
            """)

            # 9. Birthdays (Per Guild? Usually Global user data, but announced per guild?)
            # Prompt: "Discord birthday notification, alert everyone when it's someones birthday."
            # Usually users set it once globally.
            await db.execute("""
                CREATE TABLE IF NOT EXISTS birthdays (
                    user_id INTEGER PRIMARY KEY,
                    day INTEGER,
                    month INTEGER
                )
            """)

            await db.commit()

    async def migrate_from_json(self):
        if not os.path.exists("guild_configs.json"):
            return

        print("Migrating guild_configs.json to SQLite...")
        try:
            with open("guild_configs.json", "r") as f:
                data = json.load(f)

            async with aiosqlite.connect(self.db_file) as db:
                for guild_id_str, config in data.items():
                    guild_id = int(guild_id_str)
                    owner_role = config.get('owner_role_id')
                    forum_chan = config.get('forum_channel_id')
                    log_chan = config.get('log_channel_id')
                    muted_role = config.get('muted_role_id')
                    allowed = json.dumps(config.get('allowed_search_channels', []))
                    mod_roles = json.dumps(config.get('mod_roles', []))

                    await db.execute("""
                        INSERT OR REPLACE INTO guild_configs
                        (guild_id, owner_role_id, forum_channel_id, log_channel_id, muted_role_id, allowed_search_channels, mod_roles)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (guild_id, owner_role, forum_chan, log_chan, muted_role, allowed, mod_roles))

                await db.commit()

            # Rename old file
            os.rename("guild_configs.json", "guild_configs.json.bak")
            print("Migration complete. Renamed JSON to .bak")

        except Exception as e:
            print(f"Migration failed: {e}")

    # --- Helper Methods ---
    async def get_guild_config(self, guild_id):
        async with aiosqlite.connect(self.db_file) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM guild_configs WHERE guild_id = ?", (guild_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                return {}

    async def update_guild_config(self, guild_id, key, value):
        # Allow dynamic updates. Note: Safe only if key is valid column.
        valid_columns = ['owner_role_id', 'forum_channel_id', 'log_channel_id', 'muted_role_id', 'allowed_search_channels', 'mod_roles']
        if key not in valid_columns:
            return False

        async with aiosqlite.connect(self.db_file) as db:
            # Check if exists
            async with db.execute("SELECT 1 FROM guild_configs WHERE guild_id = ?", (guild_id,)) as cursor:
                exists = await cursor.fetchone()

            if not exists:
                await db.execute("INSERT INTO guild_configs (guild_id) VALUES (?)", (guild_id,))

            if key in ['allowed_search_channels', 'mod_roles'] and isinstance(value, list):
                value = json.dumps(value)

            await db.execute(f"UPDATE guild_configs SET {key} = ? WHERE guild_id = ?", (value, guild_id))
            await db.commit()
        return True

db_manager = DatabaseManager()
