# Google Maps Restaurant Scraper

Playwright-based scraper that extracts restaurant information from Google Maps, with a FastAPI backend and web frontend.

## Architecture

```
frontend/          → Simple HTML UI for triggering scrapes and viewing results
backend/
  ├── main.py      → FastAPI app (REST API)
  ├── scraper.py   → Playwright scraper logic
  ├── database.py  → MySQL/RDS data layer
  └── models.py    → Pydantic models
Dockerfile         → Container image for AWS Fargate deployment
scraper.py         → Standalone CLI scraper (outputs JSON/CSV)
```

## Quick Start (Local)

```bash
pip install -r requirements.txt
playwright install chromium
```

### Standalone CLI

```bash
python scraper.py
```

Searches for restaurants on George Street, Sydney by default. Edit `SEARCH_QUERY` to change the target.

### Backend API + Frontend

```bash
# Set required environment variables
export DB_HOST=your-rds-endpoint
export DB_USER=admin
export DB_PASSWORD=your-password
export DB_NAME=gmaps_scraper  # optional, defaults to gmaps_scraper

# Start the API server
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000
```

Then open `frontend/index.html` in a browser.

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DB_HOST` | ✅ | — | MySQL/RDS endpoint |
| `DB_PORT` | ❌ | `3306` | MySQL port |
| `DB_USER` | ✅ | — | Database username |
| `DB_PASSWORD` | ✅ | — | Database password |
| `DB_NAME` | ❌ | `gmaps_scraper` | Database name |

## AWS Fargate Deployment

1. **Build & push image** via CodeBuild or locally:
   ```bash
   docker build -t gmaps-scraper .
   ```

2. **Create ECS task definition** with the environment variables above. For production, use AWS Secrets Manager:
   ```json
   "secrets": [
     {"name": "DB_PASSWORD", "valueFrom": "arn:aws:secretsmanager:..."}
   ]
   ```

3. **Run on Fargate** with a public subnet (scraper needs internet access for Google Maps).

   Recommended: 1 vCPU / 3 GB memory.

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/scrape` | Start a new scrape job |
| `GET` | `/api/jobs` | List all jobs |
| `GET` | `/api/jobs/{id}` | Get job status |
| `GET` | `/api/jobs/{id}/results` | Get scrape results |
| `GET` | `/api/search` | Search completed jobs by location |

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
