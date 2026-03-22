"""
Google Maps Restaurant Scraper
Extracts restaurant info from Google Maps using Playwright + stealth.
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
from playwright_stealth import stealth_sync

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SEARCH_QUERY = "restaurants on George Street Sydney Australia"
MAX_SCROLLS = 40  # max scroll attempts for the result list
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def random_delay(lo: float = 2.0, hi: float = 5.0):
    time.sleep(random.uniform(lo, hi))


def screenshot(page, name: str):
    path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    page.screenshot(path=path)
    log.info("Screenshot saved: %s", path)


def extract_lat_lng(url: str):
    """Try to pull lat/lng from a Google Maps URL."""
    m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", url)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", url)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None, None


def safe_text(el):
    """Return trimmed innerText of an element, or empty string."""
    if el is None:
        return ""
    txt = el.inner_text()
    return txt.strip() if txt else ""


def try_get_text(page, selector: str, timeout: int = 3000) -> str:
    """Wait briefly for a selector then return its text, or ''."""
    try:
        el = page.wait_for_selector(selector, timeout=timeout)
        return safe_text(el)
    except (PwTimeout, Exception):
        return ""


# ---------------------------------------------------------------------------
# Dismiss popups (cookie consent, sign-in, etc.)
# ---------------------------------------------------------------------------
def dismiss_popups(page):
    for btn_text in ["Accept all", "Reject all", "No thanks", "Dismiss"]:
        try:
            btn = page.get_by_role("button", name=btn_text)
            if btn.is_visible(timeout=2000):
                btn.click()
                log.info("Dismissed popup: %s", btn_text)
                random_delay(1, 2)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Scroll the results panel to load all listings
# ---------------------------------------------------------------------------
def scroll_results(page) -> int:
    """Scroll the left-side results feed until no new results appear."""
    feed = page.locator('div[role="feed"]')
    if not feed.count():
        # fallback: try scrollable div that contains result items
        feed = page.locator('div[role="main"]')
    previous_count = 0
    for i in range(MAX_SCROLLS):
        items = page.locator('div[role="feed"] > div > div > a').all()
        current_count = len(items)
        log.info("Scroll %d – listings visible: %d", i + 1, current_count)

        # Check for "end of list" marker
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
# Scrape a single restaurant detail panel
# ---------------------------------------------------------------------------
def scrape_detail(page) -> dict:
    """Extract data from the currently-open detail panel."""
    data: dict = {}

    # Name – the heading inside the detail panel
    data["name"] = try_get_text(page, 'h1')

    # Rating & review count
    rating_el = page.query_selector('div[role="img"][aria-label*="star"]')
    if rating_el:
        label = rating_el.get_attribute("aria-label") or ""
        m = re.search(r"([\d.]+)\s*star", label)
        data["rating"] = m.group(1) if m else ""
    else:
        data["rating"] = ""

    review_btn = page.query_selector('button[aria-label*="review"]')
    if review_btn:
        label = review_btn.get_attribute("aria-label") or ""
        m = re.search(r"([\d,]+)", label)
        data["review_count"] = m.group(1) if m else ""
    else:
        data["review_count"] = ""

    # Category & price range – usually right below the name
    # Appears as e.g. "Chinese restaurant · $$"
    cat_el = page.query_selector('button[jsaction*="category"]')
    data["category"] = safe_text(cat_el) if cat_el else ""

    price_el = page.query_selector('span[aria-label*="Price"]')
    if price_el:
        data["price_range"] = price_el.get_attribute("aria-label") or safe_text(price_el)
    else:
        data["price_range"] = ""

    # Address
    addr_el = page.query_selector('button[data-item-id="address"] div.fontBodyMedium')
    if not addr_el:
        addr_el = page.query_selector('button[aria-label*="Address"]')
    data["address"] = (addr_el.get_attribute("aria-label") or safe_text(addr_el)).replace("Address: ", "") if addr_el else ""

    # Hours – expand if needed
    hours_el = page.query_selector('div[aria-label*="hour" i]')
    if not hours_el:
        # try clicking the hours row to expand
        hours_row = page.query_selector('button[data-item-id*="oh"]')
        if hours_row:
            try:
                hours_row.click()
                random_delay(0.5, 1.0)
                hours_el = page.query_selector('div[aria-label*="hour" i]')
            except Exception:
                pass
    data["hours"] = (hours_el.get_attribute("aria-label") or safe_text(hours_el)) if hours_el else ""

    # Phone
    phone_el = page.query_selector('button[data-item-id*="phone"] div.fontBodyMedium')
    if not phone_el:
        phone_el = page.query_selector('button[aria-label*="Phone"]')
    data["phone"] = (phone_el.get_attribute("aria-label") or safe_text(phone_el)).replace("Phone: ", "") if phone_el else ""

    # Website
    web_el = page.query_selector('a[data-item-id="authority"]')
    if not web_el:
        web_el = page.query_selector('a[aria-label*="Website"]')
    data["website"] = (web_el.get_attribute("href") or "") if web_el else ""

    # Services (dine-in / takeaway / delivery)
    services = []
    for svc_el in page.query_selector_all('div[role="region"] li'):
        txt = safe_text(svc_el)
        if txt:
            services.append(txt)
    # fallback: look for aria-labels mentioning service options
    if not services:
        for attr_name in ["Dine-in", "Takeaway", "Takeout", "Delivery", "No-contact delivery"]:
            el = page.query_selector(f'span[aria-label*="{attr_name}" i]')
            if el:
                label = el.get_attribute("aria-label") or safe_text(el)
                if label:
                    services.append(label)
    data["services"] = ", ".join(services)

    # Price per person
    price_pp = page.query_selector('span[aria-label*="per person" i]')
    data["price_per_person"] = (price_pp.get_attribute("aria-label") or safe_text(price_pp)) if price_pp else ""

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
    restaurants: list[dict] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
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
        stealth_sync(page)

        # 1. Open Google Maps and search
        log.info("Opening Google Maps...")
        page.goto("https://www.google.com/maps", wait_until="domcontentloaded", timeout=30000)
        random_delay()
        dismiss_popups(page)
        screenshot(page, "01_maps_home")

        search_box = page.locator('#searchboxinput')
        search_box.fill(SEARCH_QUERY)
        search_box.press("Enter")
        log.info("Searching: %s", SEARCH_QUERY)
        random_delay(3, 5)
        dismiss_popups(page)
        screenshot(page, "02_search_results")

        # 2. Scroll result list to load all restaurants
        log.info("Scrolling result list...")
        total = scroll_results(page)
        screenshot(page, "03_all_results_loaded")

        # 3. Collect listing links
        listing_els = page.locator('div[role="feed"] > div > div > a').all()
        listing_hrefs: list[str] = []
        for el in listing_els:
            href = el.get_attribute("href")
            if href:
                listing_hrefs.append(href)
        log.info("Collected %d listing URLs.", len(listing_hrefs))

        # 4. Visit each listing
        for idx, href in enumerate(listing_hrefs):
            attempt = 0
            while attempt < RETRY_LIMIT:
                attempt += 1
                try:
                    log.info("[%d/%d] (attempt %d) Opening: %s", idx + 1, len(listing_hrefs), attempt, href[:80])
                    page.goto(href, wait_until="domcontentloaded", timeout=20000)
                    random_delay()
                    dismiss_popups(page)

                    # Wait for the heading to appear
                    page.wait_for_selector("h1", timeout=8000)
                    detail = scrape_detail(page)
                    log.info("  -> %s | rating=%s | reviews=%s", detail["name"], detail["rating"], detail["review_count"])
                    restaurants.append(detail)

                    if (idx + 1) % 5 == 0:
                        screenshot(page, f"04_detail_{idx+1}")
                    break  # success
                except PwTimeout:
                    log.warning("  Timeout on attempt %d for %s", attempt, href[:80])
                    if attempt == RETRY_LIMIT:
                        log.error("  Giving up on %s", href[:80])
                except Exception as exc:
                    log.warning("  Error on attempt %d: %s", attempt, exc)
                    if attempt == RETRY_LIMIT:
                        log.error("  Giving up on %s", href[:80])

            random_delay(1, 3)

        browser.close()

    # 5. Save results
    log.info("Scraped %d restaurants total.", len(restaurants))

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(restaurants, f, ensure_ascii=False, indent=2)
    log.info("Saved %s", OUTPUT_JSON)

    if restaurants:
        fieldnames = list(restaurants[0].keys())
        with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(restaurants)
        log.info("Saved %s", OUTPUT_CSV)


if __name__ == "__main__":
    run()
