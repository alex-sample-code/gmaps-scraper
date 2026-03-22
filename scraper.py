"""
Google Maps Restaurant Scraper v2
- Incremental save (won't lose data on crash)
- Fixed review_count & price_per_person extraction
- Robust selectors based on actual Google Maps DOM
"""

import csv
import json
import logging
import os
import random
import re
import time
from urllib.parse import unquote

from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
from playwright_stealth import Stealth

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SEARCH_QUERY = "restaurants on George Street Sydney Australia"
MAX_SCROLLS = 50
RETRY_LIMIT = 3
OUTPUT_JSON = "restaurants.json"
OUTPUT_CSV = "restaurants.csv"
SCREENSHOT_DIR = "screenshots"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

os.makedirs(SCREENSHOT_DIR, exist_ok=True)


def random_delay(lo: float = 2.0, hi: float = 5.0):
    time.sleep(random.uniform(lo, hi))


def screenshot(page, name: str):
    path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    try:
        page.screenshot(path=path)
        log.info("Screenshot saved: %s", path)
    except Exception:
        pass


def extract_lat_lng(url: str):
    m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", url)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", url)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None, None


def safe_text(el):
    if el is None:
        return ""
    try:
        txt = el.inner_text()
        return txt.strip() if txt else ""
    except Exception:
        return ""


def try_get_text(page, selector: str, timeout: int = 3000) -> str:
    try:
        el = page.wait_for_selector(selector, timeout=timeout)
        return safe_text(el)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Incremental save
# ---------------------------------------------------------------------------
def save_results(restaurants: list):
    """Save current results to JSON and CSV (overwrites each time)."""
    if not restaurants:
        return
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(restaurants, f, ensure_ascii=False, indent=2)
    fieldnames = list(restaurants[0].keys())
    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(restaurants)


# ---------------------------------------------------------------------------
# Dismiss popups
# ---------------------------------------------------------------------------
def dismiss_popups(page):
    for btn_text in ["Accept all", "Reject all", "No thanks", "Dismiss"]:
        try:
            btn = page.get_by_role("button", name=btn_text)
            if btn.is_visible(timeout=1500):
                btn.click()
                log.info("Dismissed popup: %s", btn_text)
                random_delay(0.5, 1)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Scroll results
# ---------------------------------------------------------------------------
def scroll_results(page) -> int:
    feed = page.locator('div[role="feed"]')
    if not feed.count():
        feed = page.locator('div[role="main"]')
    previous_count = 0
    for i in range(MAX_SCROLLS):
        items = page.locator('div[role="feed"] > div > div > a').all()
        current_count = len(items)
        log.info("Scroll %d – listings visible: %d", i + 1, current_count)

        end_marker = page.locator("text=You've reached the end of the list")
        if end_marker.count() > 0:
            log.info("Reached end-of-list marker.")
            break
        if current_count == previous_count and i > 2:
            log.info("No new results after scroll, stopping.")
            break
        previous_count = current_count
        feed.evaluate("el => el.scrollTop = el.scrollHeight")
        random_delay(1.5, 3.0)

    final = page.locator('div[role="feed"] > div > div > a').all()
    log.info("Total listings found: %d", len(final))
    return len(final)


# ---------------------------------------------------------------------------
# Scrape detail - v2 with fixed selectors
# ---------------------------------------------------------------------------
def scrape_detail(page) -> dict:
    data = {}

    # Name
    data["name"] = try_get_text(page, "h1", timeout=5000)

    # Rating & review count - from the line like "4.6 ★★★★★ (2,306) · A$20-40"
    # The rating is in a span with aria-label like "4.6 stars"
    try:
        # Get the info line text below the name
        info_line = page.query_selector('div.F7nice')
        if info_line:
            full_text = safe_text(info_line)
            # Extract rating
            rating_match = re.search(r'([\d.]+)', full_text)
            data["rating"] = rating_match.group(1) if rating_match else ""
            # Extract review count - in parentheses
            review_match = re.search(r'\(([\d,]+)\)', full_text)
            data["review_count"] = review_match.group(1) if review_match else ""
        else:
            # Fallback: aria-label on star image
            star_el = page.query_selector('span[aria-label*="star"]')
            if star_el:
                label = star_el.get_attribute("aria-label") or ""
                m = re.search(r'([\d.]+)', label)
                data["rating"] = m.group(1) if m else ""
            else:
                data["rating"] = ""
            # Review count fallback
            review_el = page.query_selector('span[aria-label*="review"]')
            if review_el:
                label = review_el.get_attribute("aria-label") or ""
                m = re.search(r'([\d,]+)', label)
                data["review_count"] = m.group(1) if m else ""
            else:
                data["review_count"] = ""
    except Exception:
        data["rating"] = ""
        data["review_count"] = ""

    # Price range (from info line, e.g. "A$20-40" or "$$")
    try:
        # Look for price indicator - usually contains $ sign
        price_spans = page.query_selector_all('span[aria-label*="Price"], span[aria-label*="price"]')
        if price_spans:
            data["price_range"] = price_spans[0].get_attribute("aria-label") or safe_text(price_spans[0])
        else:
            # Try to extract from the info line
            info_el = page.query_selector('div.F7nice')
            if info_el:
                txt = safe_text(info_el)
                price_m = re.search(r'[·\·]\s*([\$A\$][\d\-\$,]+)', txt)
                data["price_range"] = price_m.group(1) if price_m else ""
            else:
                data["price_range"] = ""
    except Exception:
        data["price_range"] = ""

    # Category
    try:
        cat_btn = page.query_selector('button[jsaction*="category"]')
        if cat_btn:
            data["category"] = safe_text(cat_btn)
        else:
            # Fallback: look for the category text below name
            cat_el = page.query_selector('span.DkEaL')
            data["category"] = safe_text(cat_el) if cat_el else ""
    except Exception:
        data["category"] = ""

    # Address
    try:
        addr_el = page.query_selector('button[data-item-id="address"]')
        if addr_el:
            data["address"] = safe_text(addr_el).strip()
        else:
            addr_el = page.query_selector('[data-item-id="address"] .fontBodyMedium')
            data["address"] = safe_text(addr_el) if addr_el else ""
    except Exception:
        data["address"] = ""

    # Hours
    try:
        # Try expanding hours first
        hours_btn = page.query_selector('button[data-item-id*="oh"]')
        if hours_btn:
            # Get the summary text
            data["hours"] = safe_text(hours_btn).replace("\n", " | ")
        else:
            hours_el = page.query_selector('[aria-label*="hour" i]')
            data["hours"] = (hours_el.get_attribute("aria-label") or safe_text(hours_el)) if hours_el else ""
    except Exception:
        data["hours"] = ""

    # Phone
    try:
        phone_el = page.query_selector('button[data-item-id*="phone"]')
        if phone_el:
            data["phone"] = safe_text(phone_el).strip()
        else:
            data["phone"] = ""
    except Exception:
        data["phone"] = ""

    # Website
    try:
        web_el = page.query_selector('a[data-item-id="authority"]')
        if web_el:
            data["website"] = web_el.get_attribute("href") or ""
        else:
            web_el = page.query_selector('a[aria-label*="Website"]')
            data["website"] = (web_el.get_attribute("href") or "") if web_el else ""
    except Exception:
        data["website"] = ""

    # Services (Dine-in, Takeout, Delivery)
    try:
        services = []
        # Look for the service indicators with checkmarks
        svc_container = page.query_selector_all('div[class*="LTs0Rc"]')
        if svc_container:
            for el in svc_container:
                txt = safe_text(el)
                if txt:
                    services.append(txt)
        if not services:
            # Fallback: get text that mentions dine-in/takeout/delivery
            body_text = page.query_selector('div[role="main"]')
            if body_text:
                full = safe_text(body_text)
                for svc in ["Dine-in", "Takeout", "Takeaway", "Delivery", "No-contact delivery"]:
                    if svc.lower() in full.lower():
                        services.append(svc)
        data["services"] = ", ".join(services) if services else ""
    except Exception:
        data["services"] = ""

    # Price per person - "A$20-40 per person" / "Reported by X people"
    try:
        # Try aria-label first
        pp_el = page.query_selector('span[aria-label*="per person" i]')
        if pp_el:
            data["price_per_person"] = pp_el.get_attribute("aria-label") or safe_text(pp_el)
        else:
            # Search all text for "per person" pattern
            all_text = page.inner_text('div[role="main"]')
            pp_match = re.search(r'([\$A][\$\d\-–,\s]+per person)', all_text, re.IGNORECASE)
            if pp_match:
                data["price_per_person"] = pp_match.group(1).strip()
            else:
                data["price_per_person"] = ""
    except Exception:
        data["price_per_person"] = ""

    # URL & coordinates
    url = page.url
    data["url"] = url
    lat, lng = extract_lat_lng(url)
    data["lat"] = lat
    data["lng"] = lng

    return data


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run():
    restaurants: list = []

    # Load existing results if resuming
    if os.path.exists(OUTPUT_JSON):
        try:
            with open(OUTPUT_JSON, "r", encoding="utf-8") as f:
                restaurants = json.load(f)
            log.info("Loaded %d existing results from %s", len(restaurants), OUTPUT_JSON)
        except Exception:
            pass

    seen_urls = {r.get("url", "") for r in restaurants}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ])
        context = browser.new_context(
            locale="en-AU",
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        stealth = Stealth()
        stealth.apply_stealth_sync(page)

        # 1. Open Google Maps and search
        log.info("Opening Google Maps...")
        page.goto("https://www.google.com/maps", wait_until="domcontentloaded", timeout=30000)
        random_delay(2, 4)
        dismiss_popups(page)
        screenshot(page, "01_maps_home")

        # Find search box
        search_box = None
        for sel in ['#searchboxinput', 'input[name="q"]', 'input[aria-label*="Search"]']:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible(timeout=3000):
                    search_box = loc.first
                    log.info("Found search box: %s", sel)
                    break
            except Exception:
                continue
        if search_box is None:
            log.error("Could not find search box!")
            browser.close()
            return

        search_box.click()
        random_delay(0.3, 0.8)
        search_box.fill(SEARCH_QUERY)
        search_box.press("Enter")
        log.info("Searching: %s", SEARCH_QUERY)
        random_delay(3, 5)
        dismiss_popups(page)
        screenshot(page, "02_search_results")

        # 2. Scroll
        log.info("Scrolling result list...")
        scroll_results(page)
        screenshot(page, "03_all_results")

        # 3. Collect listing links
        listing_els = page.locator('div[role="feed"] > div > div > a').all()
        listing_hrefs = []
        for el in listing_els:
            href = el.get_attribute("href")
            if href and href not in seen_urls:
                listing_hrefs.append(href)
        log.info("New listings to scrape: %d", len(listing_hrefs))

        # 4. Visit each listing (incremental save every 5)
        for idx, href in enumerate(listing_hrefs):
            attempt = 0
            while attempt < RETRY_LIMIT:
                attempt += 1
                try:
                    log.info("[%d/%d] (attempt %d) %s", idx + 1, len(listing_hrefs), attempt, href[:90])
                    page.goto(href, wait_until="domcontentloaded", timeout=20000)
                    random_delay(1.5, 3)
                    dismiss_popups(page)
                    page.wait_for_selector("h1", timeout=8000)

                    detail = scrape_detail(page)
                    log.info("  -> %s | rating=%s | reviews=%s | price_pp=%s",
                             detail["name"], detail["rating"], detail["review_count"], detail["price_per_person"])
                    restaurants.append(detail)

                    # Incremental save every 5 entries
                    if len(restaurants) % 5 == 0:
                        save_results(restaurants)
                        log.info("  [saved %d records]", len(restaurants))

                    if (idx + 1) % 10 == 0:
                        screenshot(page, f"04_detail_{idx+1}")
                    break
                except PwTimeout:
                    log.warning("  Timeout attempt %d", attempt)
                except Exception as exc:
                    log.warning("  Error attempt %d: %s", attempt, exc)

            random_delay(1, 2.5)

        browser.close()

    # Final save
    save_results(restaurants)
    log.info("Done! Total: %d restaurants saved.", len(restaurants))


if __name__ == "__main__":
    run()
