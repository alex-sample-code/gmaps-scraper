import asyncio
import csv
import io
import json
import logging
import os
import threading
import uuid
from typing import Dict, List, Tuple

import boto3
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse

from .database import (
    create_job,
    get_job,
    get_results,
    init_db,
    insert_result,
    list_jobs,
    search_jobs,
    update_job_status,
)
from .models import ScrapeRequest, ScrapeResponse
from .scraper import run_scraper

log = logging.getLogger(__name__)

app = FastAPI(title="Google Maps Restaurant Scraper")

location_client = boto3.client("location", region_name="us-east-1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# job_id -> list of (event_loop, asyncio.Queue)
_ws_connections: Dict[str, List[Tuple]] = {}
_ws_lock = threading.Lock()

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")


@app.on_event("startup")
async def startup():
    init_db()
    log.info("Database initialised.")


# ---------------------------------------------------------------------------
# Progress callback factory
# ---------------------------------------------------------------------------

def _make_progress_callback(job_id: str):
    def callback(event_type: str, **kwargs):
        if event_type == "total_found":
            total = kwargs.get("total", 0)
            update_job_status(job_id, "running", total_found=total)
            msg = json.dumps({"type": "total_found", "total": total})

        elif event_type == "progress":
            scraped = kwargs.get("scraped", 0)
            total = kwargs.get("total", 0)
            current = kwargs.get("current", "")
            data = kwargs.get("data", {})
            insert_result(job_id, data)
            update_job_status(job_id, "running", scraped_count=scraped)
            msg = json.dumps(
                {"type": "progress", "scraped": scraped, "total": total, "current": current}
            )

        elif event_type == "completed":
            total = kwargs.get("total", 0)
            update_job_status(job_id, "completed", scraped_count=total)
            msg = json.dumps({"type": "completed", "total": total})

        elif event_type == "error":
            message = kwargs.get("message", "Unknown error")
            update_job_status(job_id, "failed", error_message=message)
            msg = json.dumps({"type": "error", "message": message})

        else:
            return

        # Broadcast to all connected WebSocket clients for this job
        with _ws_lock:
            connections = list(_ws_connections.get(job_id, []))

        for loop, queue in connections:
            try:
                asyncio.run_coroutine_threadsafe(queue.put(msg), loop)
            except Exception as exc:
                log.warning("WS send failed: %s", exc)

    return callback


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def serve_frontend():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except FileNotFoundError:
        return HTMLResponse("<h1>Frontend not found</h1>", status_code=404)


@app.post("/api/scrape", response_model=ScrapeResponse)
async def start_scrape(request: ScrapeRequest):
    job_id = str(uuid.uuid4())
    search_query = f"restaurants on {request.street} {request.city} {request.country}"

    create_job(job_id, search_query, request.country, request.city, request.street)

    callback = _make_progress_callback(job_id)

    def _run():
        run_scraper(
            search_query=search_query,
            max_results=request.max_results,
            progress_callback=callback,
        )

    thread = threading.Thread(target=_run, daemon=True, name=f"scraper-{job_id[:8]}")
    thread.start()

    return ScrapeResponse(job_id=job_id, status="started", search_query=search_query)


@app.get("/api/jobs")
async def list_all_jobs():
    jobs = list_jobs()
    return {
        "jobs": [
            {
                "id": j["id"],
                "search_query": j["search_query"],
                "status": j["status"],
                "total_found": j["total_found"],
                "scraped": j["scraped_count"],
                "created_at": j["created_at"],
            }
            for j in jobs
        ]
    }


@app.get("/api/search")
async def search_existing(country: str = "", city: str = "", street: str = ""):
    jobs = search_jobs(country=country, city=city, street=street)
    result = []
    for j in jobs:
        results = get_results(j["id"])
        result.append(
            {
                "id": j["id"],
                "search_query": j["search_query"],
                "status": j["status"],
                "country": j["country"],
                "city": j["city"],
                "street": j["street"],
                "total_found": j["total_found"],
                "scraped": j["scraped_count"],
                "created_at": j["created_at"],
                "completed_at": j["completed_at"],
                "results": [
                    {
                        "name": r["name"],
                        "rating": r["rating"],
                        "review_count": r["review_count"],
                        "price_range": r["price_range"],
                        "category": r["category"],
                        "address": r["address"],
                        "hours": r["hours"],
                        "phone": r["phone"],
                        "website": r["website"],
                        "services": r["services"],
                        "price_per_person": r["price_per_person"],
                        "url": r["url"],
                        "lat": r["lat"],
                        "lng": r["lng"],
                    }
                    for r in results
                ],
            }
        )
    return {"jobs": result}


@app.get("/api/jobs/{job_id}")
async def get_job_detail(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    results = get_results(job_id)
    return {
        "id": job["id"],
        "status": job["status"],
        "search_query": job["search_query"],
        "country": job["country"],
        "city": job["city"],
        "street": job["street"],
        "total_found": job["total_found"],
        "scraped": job["scraped_count"],
        "error_message": job["error_message"],
        "created_at": job["created_at"],
        "completed_at": job["completed_at"],
        "results": [
            {
                "name": r["name"],
                "rating": r["rating"],
                "review_count": r["review_count"],
                "price_range": r["price_range"],
                "category": r["category"],
                "address": r["address"],
                "hours": r["hours"],
                "phone": r["phone"],
                "website": r["website"],
                "services": r["services"],
                "price_per_person": r["price_per_person"],
                "url": r["url"],
                "lat": r["lat"],
                "lng": r["lng"],
            }
            for r in results
        ],
    }


@app.get("/api/jobs/{job_id}/export")
async def export_job(job_id: str, format: str = "csv"):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    results = get_results(job_id)

    if format == "csv":
        output = io.StringIO()
        fieldnames = [
            "name", "rating", "review_count", "price_range", "category",
            "address", "hours", "phone", "website", "services",
            "price_per_person", "url", "lat", "lng",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
        output.seek(0)
        filename = f"restaurants_{job_id[:8]}.csv"
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    raise HTTPException(status_code=400, detail="Unsupported format")


# ---------------------------------------------------------------------------
# AWS Location Service endpoints
# ---------------------------------------------------------------------------

@app.get("/api/places/suggest")
async def suggest_places(text: str, max_results: int = 8):
    resp = location_client.search_place_index_for_suggestions(
        IndexName="gmaps-scraper-places",
        Text=text,
        MaxResults=max_results,
    )
    return {"suggestions": [r["Text"] for r in resp["Results"]]}


@app.get("/api/places/search")
async def search_place(text: str):
    resp = location_client.search_place_index_for_text(
        IndexName="gmaps-scraper-places",
        Text=text,
        MaxResults=1,
    )
    if resp["Results"]:
        place = resp["Results"][0]["Place"]
        return {
            "country": place.get("Country", ""),
            "region": place.get("Region", ""),
            "city": place.get("Municipality", "") or place.get("SubRegion", ""),
            "street": place.get("Street", ""),
            "label": place.get("Label", ""),
            "lat": place["Geometry"]["Point"][1],
            "lng": place["Geometry"]["Point"][0],
        }
    return {"error": "Not found"}


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    await websocket.accept()

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    with _ws_lock:
        _ws_connections.setdefault(job_id, []).append((loop, queue))

    try:
        # Send current status immediately so the client can sync
        job = get_job(job_id)
        if job:
            await websocket.send_json(
                {
                    "type": "status",
                    "status": job["status"],
                    "scraped": job["scraped_count"],
                    "total": job["total_found"],
                }
            )

        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_text(msg)
                parsed = json.loads(msg)
                if parsed.get("type") in ("completed", "error"):
                    break
            except asyncio.TimeoutError:
                # keepalive ping
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break

    except WebSocketDisconnect:
        pass
    finally:
        with _ws_lock:
            conns = _ws_connections.get(job_id, [])
            _ws_connections[job_id] = [(l, q) for l, q in conns if q is not queue]
            if not _ws_connections[job_id]:
                del _ws_connections[job_id]
