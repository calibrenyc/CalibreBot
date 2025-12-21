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

# Sport Key Mapping
# User Friendly -> API Key
SPORT_MAPPING = {
    "NFL": "americanfootball_nfl",
    "NBA": "basketball_nba",
    "NHL": "icehockey_nhl",
    "MLB": "baseball_mlb",
    "Soccer": "soccer_epl", # Defaulting to EPL as requested major soccer
    "UFC": "mma_mixed_martial_arts",
    "Boxing": "boxing_boxing"
}

# Reverse Mapping for display
# API Key -> User Friendly
REVERSE_MAPPING = {v: k for k, v in SPORT_MAPPING.items()}

class OddsAPIClient:
    def __init__(self):
        self.api_key = API_KEY
        self._cache = {} # Key: (endpoint, sport), Value: {'data': ..., 'timestamp': ...}
        self.cache_duration = 600 # 10 minutes

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

    async def get_odds(self, sport_key, regions='us', markets='h2h,spreads,totals', oddsFormat='american'):
        """
        Fetches odds for a specific sport.
        Uses caching to avoid rate limits.
        """
        cache_key = f"odds_{sport_key}"
        now = time.time()

        # Check Cache
        if cache_key in self._cache:
            entry = self._cache[cache_key]
            if now - entry['timestamp'] < self.cache_duration:
                logger.debug(f"Serving {sport_key} odds from cache.")
                return entry['data']

        # Fetch from API
        url = f"{BASE_URL}/{sport_key}/odds"
        params = {
            'regions': regions,
            'markets': markets,
            'oddsFormat': oddsFormat,
            'bookmakers': 'draftkings' # Specifically requesting DraftKings
        }

        logger.info(f"Fetching fresh odds for {sport_key}...")
        data = await self._fetch(url, params)

        if data:
            self._cache[cache_key] = {'data': data, 'timestamp': now}

        return data

    async def get_scores(self, sport_key, daysFrom=3):
        """
        Fetches scores for completed games to settle bets.
        """
        # Scores usually need to be fresh, but we can cache for a shorter time e.g. 5 mins
        # or just rely on the calling loop frequency. Let's cache for 5 mins.
        cache_key = f"scores_{sport_key}"
        now = time.time()

        if cache_key in self._cache:
            entry = self._cache[cache_key]
            if now - entry['timestamp'] < 300: # 5 mins
                return entry['data']

        url = f"{BASE_URL}/{sport_key}/scores"
        params = {
            'daysFrom': daysFrom
        }

        logger.info(f"Fetching scores for {sport_key}...")
        data = await self._fetch(url, params)

        if data:
            self._cache[cache_key] = {'data': data, 'timestamp': now}

        return data

# Global instance
sports_client = OddsAPIClient()
