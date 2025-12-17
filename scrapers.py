import cloudscraper
from bs4 import BeautifulSoup
import urllib.parse
import re
# Try importing the new 'ddgs' package, fallback to old 'duckduckgo_search' if needed
try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        raise ImportError("Could not import 'ddgs' or 'duckduckgo_search'. Please run 'pip install -r requirements.txt'.")

# --- Configuration ---
ONLINE_FIX_URL = "https://online-fix.me/index.php?do=search"

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
    
    # Remove CS.RIN.RU common prefixes/suffixes
    title = title.replace("CS.RIN.RU - Steam Underground Community", "")
    title = title.replace(" • View topic -", "")
    title = title.replace("View topic -", "")
    title = title.replace("CS RIN - Steam Underground", "")
    
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

def search_cs_rin(query):
    """
    Searches cs.rin.ru/forum using ddgs (DuckDuckGo Search) library.
    """
    results = []
    print(f"[Scraper] Searching CS.RIN.RU (via DDGS) for '{query}'...")
    
    try:
        search_query = f'site:cs.rin.ru/forum {query}'
        
        # Use DDGS context manager
        # Note: DDGS().text() returns an iterator of dicts
        with DDGS() as ddgs:
            ddg_results = ddgs.text(search_query, max_results=10)
            
            for r in ddg_results:
                raw_title = r.get('title')
                href = r.get('href')
                
                # Verify it is actually from cs.rin.ru and is a topic
                if href and "cs.rin.ru" in href and "viewtopic.php" in href:
                     title = clean_title(raw_title)
                     
                     if not title:
                         continue # Skip if empty or blacklisted
                         
                     results.append({
                        "title": title,
                        "link": href,
                        "source": "cs.rin.ru"
                     })

    except Exception as e:
        print(f"[Scraper] Error searching cs.rin.ru via DDGS: {e}")
        
    print(f"[Scraper] CS.RIN.RU found {len(results)} results.")
    return results

if __name__ == "__main__":
    # Test execution
    print("Testing Scrapers...")
    of_res = search_online_fix("cyberpunk")
    for r in of_res[:3]:
        print(r)
        
    # Test CS RIN
    cs_res = search_cs_rin("elden ring")
    for r in cs_res[:3]:
        print(r)
