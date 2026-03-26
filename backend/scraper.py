"""
Google Maps scraper - refactored for backend use.
Core logic reused from the root scraper.py; accepts dynamic params + progress callback.
"""

import logging
import random
import re
import time
from typing import Callable, List, Optional

from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
from playwright_stealth import Stealth

log = logging.getLogger(__name__)

RETRY_LIMIT = 3


def random_delay(lo: float = 2.0, hi: float = 5.0):
    time.sleep(random.uniform(lo, hi))


def extract_lat_lng(url: str):
    m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", url)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", url)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None, None


def safe_text(el) -> str:
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


def dismiss_popups(page):
    for btn_text in ["Accept all", "Reject all", "No thanks", "Dismiss"]:
        try:
            btn = page.get_by_role("button", name=btn_text)
            if btn.is_visible(timeout=1500):
                btn.click()
                random_delay(0.5, 1.0)
        except Exception:
            pass


def scroll_results(page, max_results: int) -> int:
    feed = page.locator('div[role="feed"]')
    if not feed.count():
        feed = page.locator('div[role="main"]')
    previous_count = 0
    for i in range(50):
        items = page.locator('div[role="feed"] > div > div > a').all()
        current_count = len(items)
        log.info("Scroll %d – listings visible: %d", i + 1, current_count)

        if current_count >= max_results:
            log.info("Reached max_results cap: %d", max_results)
            break

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
    count = min(len(final), max_results)
    log.info("Total listings found: %d (capped at %d)", len(final), count)
    return count


def scrape_detail(page) -> dict:
    data = {}

    # Name
    data["name"] = try_get_text(page, "h1", timeout=5000)

    # Rating & review count
    try:
        info_line = page.query_selector("div.F7nice")
        if info_line:
            full_text = safe_text(info_line)
            rating_match = re.search(r"([\d.]+)", full_text)
            data["rating"] = rating_match.group(1) if rating_match else ""
            review_match = re.search(r"\(([\d,]+)\)", full_text)
            data["review_count"] = review_match.group(1) if review_match else ""
        else:
            star_el = page.query_selector('span[aria-label*="star"]')
            if star_el:
                label = star_el.get_attribute("aria-label") or ""
                m = re.search(r"([\d.]+)", label)
                data["rating"] = m.group(1) if m else ""
            else:
                data["rating"] = ""
            review_el = page.query_selector('span[aria-label*="review"]')
            if review_el:
                label = review_el.get_attribute("aria-label") or ""
                m = re.search(r"([\d,]+)", label)
                data["review_count"] = m.group(1) if m else ""
            else:
                data["review_count"] = ""
    except Exception:
        data["rating"] = ""
        data["review_count"] = ""

    # Price range
    try:
        price_spans = page.query_selector_all(
            'span[aria-label*="Price"], span[aria-label*="price"]'
        )
        if price_spans:
            data["price_range"] = price_spans[0].get_attribute("aria-label") or safe_text(
                price_spans[0]
            )
        else:
            info_el = page.query_selector("div.F7nice")
            if info_el:
                txt = safe_text(info_el)
                price_m = re.search(r"[·\xb7]\s*([\$A\$][\d\-\$,]+)", txt)
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
            cat_el = page.query_selector("span.DkEaL")
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
        hours_btn = page.query_selector('button[data-item-id*="oh"]')
        if hours_btn:
            data["hours"] = safe_text(hours_btn).replace("\n", " | ")
        else:
            hours_el = page.query_selector('[aria-label*="hour" i]')
            data["hours"] = (
                (hours_el.get_attribute("aria-label") or safe_text(hours_el))
                if hours_el
                else ""
            )
    except Exception:
        data["hours"] = ""

    # Phone
    try:
        phone_el = page.query_selector('button[data-item-id*="phone"]')
        data["phone"] = safe_text(phone_el).strip() if phone_el else ""
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

    # Services
    try:
        services = []
        svc_els = page.query_selector_all('div[class*="LTs0Rc"]')
        if svc_els:
            for el in svc_els:
                txt = safe_text(el)
                if txt:
                    services.append(txt)
        if not services:
            body = page.query_selector('div[role="main"]')
            if body:
                full = safe_text(body)
                for svc in ["Dine-in", "Takeout", "Takeaway", "Delivery", "No-contact delivery"]:
                    if svc.lower() in full.lower():
                        services.append(svc)
        data["services"] = ", ".join(services)
    except Exception:
        data["services"] = ""

    # Price per person
    try:
        pp_el = page.query_selector('span[aria-label*="per person" i]')
        if pp_el:
            data["price_per_person"] = pp_el.get_attribute("aria-label") or safe_text(pp_el)
        else:
            all_text = page.inner_text('div[role="main"]')
            pp_match = re.search(r"([\$A][\$\d\-\u2013,\s]+per person)", all_text, re.IGNORECASE)
            data["price_per_person"] = pp_match.group(1).strip() if pp_match else ""
    except Exception:
        data["price_per_person"] = ""

    # URL & coordinates
    url = page.url
    data["url"] = url
    lat, lng = extract_lat_lng(url)
    data["lat"] = lat
    data["lng"] = lng

    return data


def run_scraper(
    search_query: str,
    max_results: int,
    progress_callback: Callable,
    stop_event=None,
) -> List[dict]:
    """
    Run the scraper synchronously (call this from a background thread).

    progress_callback(event_type, **kwargs):
      - "total_found"  kwargs: total
      - "progress"     kwargs: scraped, total, current, data
      - "completed"    kwargs: total
      - "error"        kwargs: message
    """
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )
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

            log.info("Opening Google Maps for query: %s", search_query)
            page.goto(
                "https://www.google.com/maps",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            random_delay(2, 4)
            dismiss_popups(page)

            # Find search box
            search_box = None
            for sel in [
                "#searchboxinput",
                'input[name="q"]',
                'input[aria-label*="Search"]',
            ]:
                try:
                    loc = page.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible(timeout=3000):
                        search_box = loc.first
                        break
                except Exception:
                    continue

            if search_box is None:
                progress_callback("error", message="Could not find Google Maps search box")
                browser.close()
                return []

            search_box.click()
            random_delay(0.3, 0.8)
            search_box.fill(search_query)
            search_box.press("Enter")
            log.info("Searching: %s", search_query)
            random_delay(3, 5)
            dismiss_popups(page)

            # Scroll to load all results
            total_count = scroll_results(page, max_results)
            progress_callback("total_found", total=total_count)

            # Collect listing URLs
            listing_els = page.locator('div[role="feed"] > div > div > a').all()
            listing_hrefs = [
                el.get_attribute("href")
                for el in listing_els
                if el.get_attribute("href")
            ]
            listing_hrefs = listing_hrefs[:max_results]
            log.info("Listings to scrape: %d", len(listing_hrefs))

            results = []
            for idx, href in enumerate(listing_hrefs):
                if stop_event and stop_event.is_set():
                    log.info("Stop event set, halting scraper.")
                    break

                attempt = 0
                success = False
                while attempt < RETRY_LIMIT and not success:
                    attempt += 1
                    try:
                        log.info(
                            "[%d/%d] attempt %d: %s",
                            idx + 1,
                            len(listing_hrefs),
                            attempt,
                            href[:80],
                        )
                        page.goto(href, wait_until="domcontentloaded", timeout=20000)
                        random_delay(1.5, 3.0)
                        dismiss_popups(page)
                        page.wait_for_selector("h1", timeout=8000)

                        detail = scrape_detail(page)
                        results.append(detail)
                        success = True

                        progress_callback(
                            "progress",
                            scraped=len(results),
                            total=len(listing_hrefs),
                            current=detail.get("name", ""),
                            data=detail,
                        )
                    except PwTimeout:
                        log.warning("Timeout on attempt %d for %s", attempt, href[:60])
                    except Exception as exc:
                        log.warning("Error on attempt %d: %s", attempt, exc)

                random_delay(1.0, 2.5)

            browser.close()
            progress_callback("completed", total=len(results))
            return results

    except Exception as exc:
        log.error("Scraper fatal error: %s", exc, exc_info=True)
        progress_callback("error", message=str(exc))
        return []
