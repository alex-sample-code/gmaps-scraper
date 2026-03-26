# Google Maps Scraper - Full Stack Application

## Architecture

```
frontend/index.html  →  Backend API (FastAPI)  →  Playwright Scraper
     ↑                        ↓
     └── WebSocket ← Progress Updates
```

## Tech Stack
- **Frontend**: Single HTML file with vanilla JS + Tailwind CSS (CDN)
- **Backend**: FastAPI (Python 3.11+), SQLite, WebSocket
- **Scraper**: Playwright (refactored from existing scraper.py)

## API Endpoints

### POST /api/scrape
Start a new scraping job.

**Request:**
```json
{
  "country": "Australia",
  "city": "Sydney", 
  "street": "George Street",
  "max_results": 50
}
```

**Response:**
```json
{
  "job_id": "uuid-string",
  "status": "started",
  "search_query": "restaurants on George Street Sydney Australia"
}
```

### GET /api/jobs
List all scraping jobs.

**Response:**
```json
{
  "jobs": [
    {
      "id": "uuid",
      "search_query": "restaurants on George Street Sydney Australia",
      "status": "running|completed|failed",
      "total_found": 34,
      "scraped": 20,
      "created_at": "2026-03-26T01:40:00Z"
    }
  ]
}
```

### GET /api/jobs/{job_id}
Get job details with results.

**Response:**
```json
{
  "id": "uuid",
  "status": "completed",
  "search_query": "...",
  "total_found": 34,
  "scraped": 34,
  "results": [
    {
      "name": "Din Tai Fung",
      "rating": "4.5",
      "review_count": "1,234",
      "price_range": "$$",
      "category": "Chinese restaurant",
      "address": "123 George St, Sydney NSW 2000",
      "hours": "Mon: 11am-9pm...",
      "phone": "02 1234 5678",
      "website": "https://...",
      "services": "Dine-in, Takeaway, Delivery",
      "price_per_person": "$150-200 per person",
      "url": "https://google.com/maps/...",
      "lat": -33.8688,
      "lng": 151.2093
    }
  ]
}
```

### GET /api/jobs/{job_id}/export?format=csv
Export results as CSV file download.

### WebSocket /ws/{job_id}
Real-time progress updates.

**Messages from server:**
```json
{"type": "progress", "scraped": 5, "total": 34, "current": "Din Tai Fung"}
{"type": "completed", "total": 34}
{"type": "error", "message": "..."}
```

## Frontend Requirements

### Page Layout (Single Page)
1. **Header**: "Google Maps Restaurant Scraper" title
2. **Input Form**:
   - Country dropdown (预置常用国家: Australia, US, UK, Canada, Japan, China, etc.)
   - City text input
   - Street text input  
   - Max results slider (10-100, default 50)
   - "Start Scraping" button
3. **Job List**: Show all jobs with status badges
4. **Results Panel**: 
   - Progress bar (during scraping)
   - Results table (name, rating, reviews, price, address, phone, website)
   - Export CSV button
   - Map view link for each result

### UI Style
- Clean, modern, dark theme
- Tailwind CSS via CDN
- Responsive
- No build step required

## Backend Structure

```
backend/
  main.py          # FastAPI app, routes, WebSocket
  scraper.py       # Refactored scraper (async, accepts params)
  database.py      # SQLite operations
  models.py        # Pydantic models
```

## Database Schema (SQLite)

### jobs table
| Column | Type | Description |
|--------|------|-------------|
| id | TEXT (UUID) | Primary key |
| search_query | TEXT | Full search string |
| country | TEXT | Country name |
| city | TEXT | City name |
| street | TEXT | Street name |
| status | TEXT | pending/running/completed/failed |
| total_found | INTEGER | Total listings found |
| scraped_count | INTEGER | Successfully scraped count |
| error_message | TEXT | Error details if failed |
| created_at | DATETIME | Job creation time |
| completed_at | DATETIME | Job completion time |

### results table
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Auto-increment PK |
| job_id | TEXT | Foreign key to jobs |
| name | TEXT | Restaurant name |
| rating | TEXT | Rating string |
| review_count | TEXT | Review count |
| price_range | TEXT | Price range |
| category | TEXT | Category |
| address | TEXT | Full address |
| hours | TEXT | Operating hours |
| phone | TEXT | Phone number |
| website | TEXT | Website URL |
| services | TEXT | Services offered |
| price_per_person | TEXT | Price per person |
| url | TEXT | Google Maps URL |
| lat | REAL | Latitude |
| lng | REAL | Longitude |

## Key Implementation Notes

1. **Scraper runs in background thread** - FastAPI endpoint starts scraper in a thread, returns job_id immediately
2. **Progress via WebSocket** - Scraper sends progress updates through WebSocket as it processes each restaurant
3. **Graceful error handling** - If scraper fails mid-way, save whatever was collected, mark job as failed
4. **Reuse existing scraper logic** - The core scraping functions (scroll_results, scrape_detail, etc.) from scraper.py should be reused, just wrapped in async-compatible code
5. **Static files** - FastAPI serves frontend/index.html as static file
6. **CORS** - Enable CORS for development
