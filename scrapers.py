import cloudscraper
from bs4 import BeautifulSoup
import re
import os
import logger

# --- Configuration ---
ONLINE_FIX_URL = "https://online-fix.me/index.php?do=search"
FITGIRL_URL = "https://fitgirl-repacks.site/"

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
    logger.info(f"[Scraper] Searching Online-Fix for '{query}'...")
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
            logger.error(f"[Scraper] Online-fix search failed with status: {response.status_code}")
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
                logger.error(f"[Scraper] Error parsing online-fix article: {e}")
                continue
                
    except Exception as e:
        logger.error(f"[Scraper] Error searching online-fix: {e}")
        
    logger.info(f"[Scraper] Online-Fix found {len(results)} results.")
    return results

def search_fitgirl(query):
    """
    Searches fitgirl-repacks.site for the query.
    """
    results = []
    logger.info(f"[Scraper] Searching FitGirl for '{query}'...")
    
    try:
        scraper = cloudscraper.create_scraper()

        params = {
            's': query
        }

        response = scraper.get(FITGIRL_URL, params=params)
        if response.status_code != 200:
            logger.error(f"[Scraper] FitGirl search failed with status: {response.status_code}")
            return results

        soup = BeautifulSoup(response.text, 'html.parser')

        # Results are in h1.entry-title > a
        titles = soup.select("h1.entry-title > a")

        for t in titles:
            try:
                raw_title = t.get_text(strip=True)
                link = t['href']
                
                title = clean_title(raw_title)

                if not title:
                    continue

                results.append({
                    "title": title,
                    "link": link,
                    "source": "fitgirl-repacks.site"
                })
            except Exception as e:
                logger.error(f"[Scraper] Error parsing fitgirl title: {e}")
                continue

    except Exception as e:
        logger.error(f"[Scraper] Error searching fitgirl: {e}")
        
    logger.info(f"[Scraper] FitGirl found {len(results)} results.")
    return results

if __name__ == "__main__":
    # Test execution
    logger.info("Testing Scrapers...")

    # of_res = search_online_fix("cyberpunk")
    # for r in of_res[:3]:
    #    logger.info(r)
        
    fg_res = search_fitgirl("cyberpunk")
    for r in fg_res[:3]:
        logger.info(r)
