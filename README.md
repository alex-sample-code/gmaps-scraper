# Google Maps Restaurant Scraper

Playwright-based scraper that extracts restaurant information from Google Maps for a given street/area.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
```

## Usage

```bash
python scraper.py
```

By default it searches for restaurants on George Street, Sydney, Australia. Edit the `SEARCH_QUERY` variable in `scraper.py` to change the target.

## Output

- `restaurants.json` - Full data in JSON format
- `restaurants.csv` - Tabular data in CSV format
- `screenshots/` - Debug screenshots taken during scraping

## Fields Extracted

| Field | Example |
|---|---|
| name | "Din Tai Fung" |
| rating | "4.5" |
| review_count | "1,234" |
| price_range | "$$" |
| category | "Chinese restaurant" |
| address | "123 George St, Sydney NSW 2000" |
| hours | "Mon: 11am-9pm, Tue: 11am-9pm, ..." |
| services | "Dine-in, Takeaway, Delivery" |
| price_per_person | "$150-200 per person" |
| phone | "02 1234 5678" |
| website | "https://example.com" |
| url | Google Maps URL |
| lat, lng | Coordinates extracted from URL |

## Notes

- Google Maps DOM structure changes frequently. Selectors use aria-label, role, and data attributes where possible.
- Random delays (2-5s) are added between actions to reduce detection risk.
- The scraper handles cookie consent popups automatically.
- A retry mechanism (up to 3 attempts) is built in for flaky page loads.
