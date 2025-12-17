import cloudscraper
from bs4 import BeautifulSoup
import re
import requests
import os

# --- Configuration ---
ONLINE_FIX_URL = "https://online-fix.me/index.php?do=search"
RUTRACKER_LOGIN_URL = "https://rutracker.org/forum/login.php"
RUTRACKER_SEARCH_URL = "https://rutracker.org/forum/tracker.php"

BLACKLIST_TITLES = {
    "Gameranger",
    "Info",
    "Login",
    "Register",
    "Main Page"
}

def clean_title(title):
    """
    Cleans up the game title by removing common scraping artifacts and non-English suffixes.
    Returns None if the title is invalid or blacklisted.
    """
    if not title:
        return None

    # Remove "по сети" (Cyrillic) and "po seti" (Latin)
    title = re.sub(r'\s+по сети', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\s+po seti', '', title, flags=re.IGNORECASE)
    
    # Remove excessive whitespace
    title = " ".join(title.split())
    
    if not title or title in BLACKLIST_TITLES:
        return None

    return title

def search_online_fix(query):
    """
    Searches online-fix.me for the query using a POST request.
    Returns a list of dicts: {'title': str, 'link': str, 'source': 'online-fix'}
    """
    results = []
    print(f"[Scraper] Searching Online-Fix for '{query}'...")
    try:
        # Create a fresh scraper instance for each request to avoid threading issues
        scraper = cloudscraper.create_scraper()
        
        data = {
            "do": "search",
            "subaction": "search",
            "story": query
        }
        
        # Use cloudscraper
        response = scraper.post(ONLINE_FIX_URL, data=data)
        if response.status_code != 200:
            print(f"[Scraper] Online-fix search failed with status: {response.status_code}")
            return results

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Select articles
        articles = soup.select("div.article")
        
        for article in articles:
            try:
                # Title is in <h2 class="title">
                title_tag = article.select_one("h2.title")
                if not title_tag:
                    continue
                
                raw_title = title_tag.get_text(strip=True)
                title = clean_title(raw_title)
                
                if not title:
                    continue

                # Link is in <a class="big-link"> or the parent <a> of h2
                link_tag = article.select_one("a.big-link")
                if not link_tag:
                    # Fallback: check parent of h2 or just any link inside
                    link_tag = title_tag.find_parent("a")
                
                if link_tag and link_tag.has_attr("href"):
                    link = link_tag["href"]
                    results.append({
                        "title": title,
                        "link": link,
                        "source": "online-fix.me"
                    })
            except Exception as e:
                print(f"[Scraper] Error parsing online-fix article: {e}")
                continue
                
    except Exception as e:
        print(f"[Scraper] Error searching online-fix: {e}")
        
    print(f"[Scraper] Online-Fix found {len(results)} results.")
    return results

# Global session for reuse (to persist login cookies)
_rutracker_session = None

def get_rutracker_session():
    global _rutracker_session
    if _rutracker_session:
        return _rutracker_session

    username = os.getenv("RUTRACKER_USER")
    password = os.getenv("RUTRACKER_PASSWORD")

    if not username or not password:
        print("[Scraper] RuTracker credentials not found.")
        return None

    print("[Scraper] Logging into RuTracker...")
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    })

    try:
        login_data = {
            'login_username': username,
            'login_password': password,
            'login': 'Вход'
        }
        resp = session.post(RUTRACKER_LOGIN_URL, data=login_data)
        if resp.status_code == 200 and 'bb_data' in session.cookies:
            print("[Scraper] RuTracker login successful.")
            _rutracker_session = session
            return session
        else:
             print("[Scraper] RuTracker login failed (Check credentials or captcha).")
             return None
    except Exception as e:
        print(f"[Scraper] RuTracker login error: {e}")
        return None

def search_rutracker(query):
    """
    Searches rutracker.org for the query using a POST request with authentication.
    """
    results = []
    print(f"[Scraper] Searching RuTracker for '{query}'...")

    session = get_rutracker_session()
    if not session:
        return results
    
    try:
        data = {
            'nm': query
        }

        # The search is a POST to tracker.php
        response = session.post(RUTRACKER_SEARCH_URL, data=data)
        
        if response.status_code != 200:
            print(f"[Scraper] RuTracker search failed with status: {response.status_code}")
            return results

        # RuTracker encoding is CP1251
        response.encoding = 'cp1251'

        soup = BeautifulSoup(response.text, 'html.parser')

        # Results are in #tor-tbl > tbody > tr
        rows = soup.select("#tor-tbl tr.tCenter.hl-tr")

        for row in rows:
            try:
                # Title link is in td.t-title-col > div.t-title > a
                title_tag = row.select_one("div.t-title a")
                if not title_tag:
                    continue
                
                raw_title = title_tag.get_text(strip=True)
                # Link is usually 'viewtopic.php?t=...'
                # Need to prepend domain
                href_suffix = title_tag['href']
                link = f"https://rutracker.org/forum/{href_suffix}"

                title = clean_title(raw_title)
                if not title:
                    continue

                results.append({
                    "title": title,
                    "link": link,
                    "source": "rutracker.org"
                })
            except Exception as e:
                print(f"[Scraper] Error parsing rutracker row: {e}")
                continue

    except Exception as e:
        print(f"[Scraper] Error searching rutracker: {e}")
        
    print(f"[Scraper] RuTracker found {len(results)} results.")
    return results

if __name__ == "__main__":
    # Test execution
    print("Testing Scrapers...")
    # NOTE: Ensure RUTRACKER_USER and RUTRACKER_PASSWORD are set in env for this to work

    # of_res = search_online_fix("cyberpunk")
    # for r in of_res[:3]:
    #    print(r)
        
    rt_res = search_rutracker("cyberpunk")
    for r in rt_res[:3]:
        print(r)
