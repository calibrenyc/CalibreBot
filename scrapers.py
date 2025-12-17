import cloudscraper
from bs4 import BeautifulSoup
import re

# --- Configuration ---
ONLINE_FIX_URL = "https://online-fix.me/index.php?do=search"
RUTOR_URL = "https://rutor.org.in/index.php?do=search"

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

def search_rutor(query):
    """
    Searches rutor.org.in for the query using a POST request.
    """
    results = []
    print(f"[Scraper] Searching Rutor for '{query}'...")
    
    try:
        scraper = cloudscraper.create_scraper()

        data = {
            "do": "search",
            "subaction": "search",
            "story": query
        }
        
        response = scraper.post(RUTOR_URL, data=data)
        if response.status_code != 200:
            print(f"[Scraper] Rutor search failed with status: {response.status_code}")
            return results

        soup = BeautifulSoup(response.text, 'html.parser')

        # Select titles
        titles = soup.select("div.dtitle > a")

        for t in titles:
            try:
                raw_title = t.get_text(strip=True)
                href = t['href']
                
                title = clean_title(raw_title)

                if not title:
                    continue

                results.append({
                    "title": title,
                    "link": href,
                    "source": "rutor.org.in"
                })
            except Exception as e:
                print(f"[Scraper] Error parsing rutor title: {e}")
                continue

    except Exception as e:
        print(f"[Scraper] Error searching rutor: {e}")
        
    print(f"[Scraper] Rutor found {len(results)} results.")
    return results

if __name__ == "__main__":
    # Test execution
    print("Testing Scrapers...")
    of_res = search_online_fix("cyberpunk")
    for r in of_res[:3]:
        print(r)
        
    # Test Rutor
    rutor_res = search_rutor("cyberpunk")
    for r in rutor_res[:3]:
        print(r)
