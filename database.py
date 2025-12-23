import aiosqlite
import json
import os
import asyncio
import logger

DB_FILE = "bot_data.db"

class DatabaseManager:
    def __init__(self):
        self.db_file = DB_FILE

    async def init_db(self):
        async with aiosqlite.connect(self.db_file) as db:
            # 1. Guild Configs
            await db.execute("""
                CREATE TABLE IF NOT EXISTS guild_configs (
                    guild_id INTEGER PRIMARY KEY,
                    owner_role_id INTEGER,
                    forum_channel_id INTEGER,
                    log_channel_id INTEGER,
                    muted_role_id INTEGER,
                    allowed_search_channels TEXT, -- JSON List
                    mod_roles TEXT -- JSON List,
                    xp_rate REAL DEFAULT 1.0
                )
            """)

            # Schema update for xp_rate if it doesn't exist (migration)
            try:
                await db.execute("ALTER TABLE guild_configs ADD COLUMN xp_rate REAL DEFAULT 1.0")
            except Exception: pass

            # 2. Flagged Words
            await db.execute("""
                CREATE TABLE IF NOT EXISTS flagged_words (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    word TEXT,
                    UNIQUE(guild_id, word)
                )
            """)

            # 3. Warnings
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

            # 4. Leveling
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

            # 5. Global Economy / Profile
            await db.execute("""
                CREATE TABLE IF NOT EXISTS global_users (
                    user_id INTEGER PRIMARY KEY,
                    balance INTEGER DEFAULT 0,
                    last_daily REAL DEFAULT 0,
                    bg_url TEXT DEFAULT NULL,
                    card_color TEXT DEFAULT '#7289da'
                )
            """)

            # --- Schema Updates for Rank Cards (v1.1) ---
            # SQLite doesn't support IF NOT EXISTS for ADD COLUMN easily.
            # We check pragma or catch duplicate column error.
            try:
                await db.execute("ALTER TABLE global_users ADD COLUMN card_bg_color TEXT DEFAULT '#2C2F33'")
            except Exception: pass

            try:
                await db.execute("ALTER TABLE global_users ADD COLUMN card_opacity REAL DEFAULT 0.5")
            except Exception: pass

            try:
                await db.execute("ALTER TABLE global_users ADD COLUMN card_font TEXT DEFAULT 'default'")
            except Exception: pass

            try:
                await db.execute("ALTER TABLE global_users ADD COLUMN bg_crop_x INTEGER DEFAULT 0")
            except Exception: pass

            try:
                await db.execute("ALTER TABLE global_users ADD COLUMN bg_crop_y INTEGER DEFAULT 0")
            except Exception: pass

            try:
                await db.execute("ALTER TABLE global_users ADD COLUMN bg_crop_w INTEGER DEFAULT 0")
            except Exception: pass

            # --- Schema Updates for Sportsbook (v2.2.1) ---
            try:
                await db.execute("ALTER TABLE active_sports_bets ADD COLUMN matchup TEXT DEFAULT NULL")
            except Exception: pass

            # --- Schema Updates for Config (v2.3.1) ---
            try:
                await db.execute("ALTER TABLE guild_configs ADD COLUMN update_log_channel_id INTEGER DEFAULT NULL")
            except Exception: pass

            # --- Schema Updates for Config (v2.3.x) ---
            try:
                await db.execute("ALTER TABLE guild_configs ADD COLUMN level_up_channel_id INTEGER DEFAULT NULL")
            except Exception: pass

            # --- Schema Updates for TCFC Config (v2.3.5) ---
            try:
                await db.execute("ALTER TABLE guild_configs ADD COLUMN tcfc_channel_id INTEGER DEFAULT NULL")
            except Exception: pass

            try:
                await db.execute("ALTER TABLE guild_configs ADD COLUMN tcfc_analyst_role_id INTEGER DEFAULT NULL")
            except Exception: pass

            # --- Schema Updates for TCFC (v2.3.0) ---
            # Fighters
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tcfc_fighters (
                    user_id INTEGER PRIMARY KEY,
                    elo INTEGER DEFAULT 1000,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    kos INTEGER DEFAULT 0,
                    rounds_fought INTEGER DEFAULT 0,
                    total_damage REAL DEFAULT 0.0
                )
            """)

            # Matches
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tcfc_matches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fighter_a INTEGER,
                    fighter_b INTEGER,
                    tournament_id TEXT,
                    status TEXT DEFAULT 'OPEN', -- OPEN, CLOSED, RESOLVED
                    winner_id INTEGER,
                    method TEXT, -- KO, DEC
                    round INTEGER,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # TCFC Bets
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tcfc_bets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    match_id INTEGER,
                    bet_type TEXT, -- WINNER, METHOD, ROUND
                    selection TEXT,
                    wager INTEGER,
                    odds REAL,
                    potential_payout INTEGER,
                    status TEXT DEFAULT 'PENDING'
                )
            """)

            # 6. Shop Items
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

            try:
                await db.execute("ALTER TABLE shop_items ADD COLUMN item_type TEXT DEFAULT 'ROLE'")
            except Exception: pass

            # 7. User Inventory (Added v2.4.1)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    guild_id INTEGER,
                    item_name TEXT,
                    purchase_date DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Seed Lucky Charm if missing (Fix for v2.4.3)
            async with db.execute("SELECT 1 FROM shop_items WHERE name = 'Lucky Charm'") as cursor:
                 if not await cursor.fetchone():
                     await db.execute("INSERT INTO shop_items (name, price, role_id, description, item_type) VALUES (?, ?, ?, ?, ?)",
                                      ('Lucky Charm', 2500, 0, 'Increases luck in Casino games!', 'LUCK'))
                 else:
                     # Update type if exists (Migration)
                     await db.execute("UPDATE shop_items SET item_type = 'LUCK' WHERE name = 'Lucky Charm'")

            # Seed Auto Slot
            async with db.execute("SELECT 1 FROM shop_items WHERE name = 'Auto Slot'") as cursor:
                 if not await cursor.fetchone():
                     await db.execute("INSERT INTO shop_items (name, price, role_id, description, item_type) VALUES (?, ?, ?, ?, ?)",
                                      ('Auto Slot', 5000, 0, 'Unlocks /autoslots command for rapid spinning.', 'UNLOCK'))
                 else:
                     await db.execute("UPDATE shop_items SET item_type = 'UNLOCK' WHERE name = 'Auto Slot'")

            # 8. Active Bets
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

            # 9. Active Sports Bets (Plugin 2.2)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS active_sports_bets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    guild_id INTEGER,
                    game_id TEXT,
                    sport_key TEXT,
                    bet_type TEXT, -- moneyline, spread, total
                    bet_selection TEXT, -- Team Name or Over/Under
                    bet_line TEXT, -- e.g. -110, +200, or -5.5
                    wager_amount INTEGER,
                    potential_payout INTEGER,
                    status TEXT DEFAULT 'PENDING', -- PENDING, WON, LOST, PUSH
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    matchup TEXT DEFAULT NULL
                )
            """)

            # 10. Birthdays
            await db.execute("""
                CREATE TABLE IF NOT EXISTS birthdays (
                    user_id INTEGER PRIMARY KEY,
                    day INTEGER,
                    month INTEGER
                )
            """)

            # 11. Global Config (e.g. RTP)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS global_config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            # 12. PvP Bets (Economy)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS pvp_bets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    challenger_id INTEGER,
                    opponent_id INTEGER,
                    amount INTEGER,
                    status TEXT DEFAULT 'PENDING', -- PENDING, ACTIVE, RESOLVED, VOID
                    challenger_vote INTEGER DEFAULT NULL,
                    opponent_vote INTEGER DEFAULT NULL,
                    winner_id INTEGER DEFAULT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await db.commit()

    async def migrate_from_json(self):
        if not os.path.exists("guild_configs.json"):
            return

        logger.info("Migrating guild_configs.json to SQLite...")
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

            os.rename("guild_configs.json", "guild_configs.json.bak")
            logger.success("Migration complete. Renamed JSON to .bak")

        except Exception as e:
            logger.error(f"Migration failed: {e}")

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
        valid_columns = ['owner_role_id', 'forum_channel_id', 'log_channel_id', 'muted_role_id', 'allowed_search_channels', 'mod_roles', 'xp_rate', 'update_log_channel_id', 'tcfc_channel_id', 'tcfc_analyst_role_id', 'level_up_channel_id']
        if key not in valid_columns:
            return False

        async with aiosqlite.connect(self.db_file) as db:
            async with db.execute("SELECT 1 FROM guild_configs WHERE guild_id = ?", (guild_id,)) as cursor:
                exists = await cursor.fetchone()

            if not exists:
                await db.execute("INSERT INTO guild_configs (guild_id) VALUES (?)", (guild_id,))

            if key in ['allowed_search_channels', 'mod_roles'] and isinstance(value, list):
                value = json.dumps(value)

            await db.execute(f"UPDATE guild_configs SET {key} = ? WHERE guild_id = ?", (value, guild_id))
            await db.commit()
        return True

    # Helper for generic adding to lists (used by legacy code)
    async def add_to_list(self, guild_id, key, item):
        config = await self.get_guild_config(guild_id)
        current_list = []
        if config.get(key):
            try:
                current_list = json.loads(config[key])
            except:
                pass

        if item not in current_list:
            current_list.append(item)
            await self.update_guild_config(guild_id, key, current_list)

    async def remove_from_list(self, guild_id, key, item):
        config = await self.get_guild_config(guild_id)
        current_list = []
        if config.get(key):
            try:
                current_list = json.loads(config[key])
            except:
                pass

        if item in current_list:
            current_list.remove(item)
            await self.update_guild_config(guild_id, key, current_list)

db_manager = DatabaseManager()
