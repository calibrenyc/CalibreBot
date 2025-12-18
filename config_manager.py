# This file is now a wrapper around the DB manager for backward compatibility
# or we can fully replace it. For now, let's keep the class interface but use DB.

import json
from database import db_manager
import asyncio

class ConfigManager:
    # We need to bridge synchronous calls (if any) to async,
    # but bot.py commands are async, so we can switch to async methods.

    # However, to minimize refactoring pain in step 1,
    # we might need to update bot.py to await these calls.
    # YES: bot.py needs to be updated to await config calls.

    async def get_guild_config(self, guild_id):
        data = await db_manager.get_guild_config(guild_id)
        if not data: return {}
        # Parse JSON lists
        if 'allowed_search_channels' in data and data['allowed_search_channels']:
            try: data['allowed_search_channels'] = json.loads(data['allowed_search_channels'])
            except: data['allowed_search_channels'] = []

        if 'mod_roles' in data and data['mod_roles']:
            try: data['mod_roles'] = json.loads(data['mod_roles'])
            except: data['mod_roles'] = []

        return data

    async def update_guild_config(self, guild_id, key, value):
        await db_manager.update_guild_config(guild_id, key, value)

    async def add_to_list(self, guild_id, key, value):
        config = await self.get_guild_config(guild_id)
        current_list = config.get(key, [])
        if value not in current_list:
            current_list.append(value)
            await db_manager.update_guild_config(guild_id, key, current_list)

    async def remove_from_list(self, guild_id, key, value):
        config = await self.get_guild_config(guild_id)
        current_list = config.get(key, [])
        if value in current_list:
            current_list.remove(value)
            await db_manager.update_guild_config(guild_id, key, current_list)

config_manager = ConfigManager()
