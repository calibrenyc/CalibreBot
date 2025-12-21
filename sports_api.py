import aiohttp
import asyncio
import time
import os
import logger
import json
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("THE_ODDS_API_KEY")
BASE_URL = "https://api.the-odds-api.com/v4/sports"
CACHE_FILE = "odds_cache.json"

# Sport Key Mapping
SPORT_MAPPING = {
    "NFL": "americanfootball_nfl",
    "NBA": "basketball_nba",
    "NHL": "icehockey_nhl",
    "MLB": "baseball_mlb",
    "Soccer": "soccer_epl",
    "UFC": "mma_mixed_martial_arts",
    "Boxing": "boxing_boxing"
}

# Reverse Mapping
REVERSE_MAPPING = {v: k for k, v in SPORT_MAPPING.items()}

class OddsAPIClient:
    def __init__(self):
        self.api_key = API_KEY
        self.cache_file = CACHE_FILE
        self._memory_cache = {}
        self.load_cache()

    def load_cache(self):
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r') as f:
                    self._memory_cache = json.load(f)
            except:
                self._memory_cache = {}

    def save_cache(self):
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(self._memory_cache, f)
        except Exception as e:
            logger.error(f"Failed to save odds cache: {e}")

    def get_sport_key(self, sport_name):
        return SPORT_MAPPING.get(sport_name)

    async def _fetch(self, url, params):
        if not self.api_key:
            logger.error("THE_ODDS_API_KEY is not set in environment.")
            return None

        params['apiKey'] = self.api_key

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        logger.error(f"Odds API Error {response.status}: {await response.text()}")
                        return None
            except Exception as e:
                logger.error(f"Failed to fetch from Odds API: {e}")
                return None

    def get_cached_odds(self, sport_key):
        """
        Returns odds ONLY from cache. No API calls.
        """
        cache_key = f"odds_{sport_key}"
        if cache_key in self._memory_cache:
            entry = self._memory_cache[cache_key]
            return entry.get('data', [])
        return []

    async def force_refresh_odds(self, sport_key=None, regions='us', markets='h2h,spreads,totals', oddsFormat='american'):
        """
        Manually triggers an API call to update the cache.
        """
        keys_to_refresh = [sport_key] if sport_key else SPORT_MAPPING.values()
        updated_count = 0

        for key in keys_to_refresh:
            url = f"{BASE_URL}/{key}/odds"
            params = {
                'regions': regions,
                'markets': markets,
                'oddsFormat': oddsFormat,
                'bookmakers': 'draftkings'
            }

            logger.info(f"🔄 Refreshing odds for {key} via API...")
            data = await self._fetch(url, params)

            if data:
                self._memory_cache[f"odds_{key}"] = {'data': data, 'timestamp': time.time()}
                updated_count += 1

            await asyncio.sleep(1) # Gentle rate limit

        self.save_cache()
        return updated_count

    # Alias for legacy compatibility, but redirects to cache
    async def get_odds(self, sport_key):
        return self.get_cached_odds(sport_key)

    async def get_scores(self, sport_key, daysFrom=3):
        """
        Fetches scores directly (Costly API call). Should be used sparingly.
        """
        url = f"{BASE_URL}/{sport_key}/scores"
        params = {'daysFrom': daysFrom}

        logger.info(f"Fetching scores for {sport_key}...")
        data = await self._fetch(url, params)
        return data

# Global instance
sports_client = OddsAPIClient()
