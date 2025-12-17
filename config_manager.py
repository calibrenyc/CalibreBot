import json
import os

CONFIG_FILE = 'guild_configs.json'

class ConfigManager:
    def __init__(self):
        self.configs = {}
        self.load_config()

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    self.configs = json.load(f)
            except json.JSONDecodeError:
                print("Error decoding config file. Starting with empty config.")
                self.configs = {}
        else:
            self.configs = {}

    def save_config(self):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.configs, f, indent=4)

    def get_guild_config(self, guild_id):
        str_id = str(guild_id)
        if str_id not in self.configs:
            self.configs[str_id] = {
                'allowed_search_channels': [],
                'forum_channel_id': None,
                'log_channel_id': None,
                'mod_roles': []
            }
            self.save_config()
        return self.configs[str_id]

    def update_guild_config(self, guild_id, key, value):
        str_id = str(guild_id)
        if str_id not in self.configs:
            self.get_guild_config(guild_id)

        self.configs[str_id][key] = value
        self.save_config()

    def add_to_list(self, guild_id, key, value):
        str_id = str(guild_id)
        if str_id not in self.configs:
            self.get_guild_config(guild_id)

        if value not in self.configs[str_id].get(key, []):
            self.configs[str_id][key].append(value)
            self.save_config()

    def remove_from_list(self, guild_id, key, value):
        str_id = str(guild_id)
        if str_id in self.configs and value in self.configs[str_id].get(key, []):
            self.configs[str_id][key].remove(value)
            self.save_config()

config_manager = ConfigManager()
