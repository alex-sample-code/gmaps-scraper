import os

import pymysql
import pymysql.cursors
from datetime import datetime
from typing import List, Optional

DB_HOST = os.environ["DB_HOST"]
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
DB_NAME = os.environ.get("DB_NAME", "gmaps_scraper")


def get_connection() -> pymysql.connections.Connection:
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def _fmt_row(row: Optional[dict]) -> Optional[dict]:
    """Convert MySQL datetime objects to ISO strings."""
    if row is None:
        return None
    result = dict(row)
    for key in ("created_at", "completed_at"):
        if result.get(key) and hasattr(result[key], "isoformat"):
            result[key] = result[key].isoformat()
    return result


def init_db():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id VARCHAR(36) PRIMARY KEY,
                    search_query VARCHAR(1000),
                    country VARCHAR(255),
                    city VARCHAR(255),
                    street VARCHAR(255),
                    status VARCHAR(50) DEFAULT 'pending',
                    total_found INT DEFAULT 0,
                    scraped_count INT DEFAULT 0,
                    error_message VARCHAR(1000),
                    created_at TIMESTAMP NULL,
                    completed_at TIMESTAMP NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS results (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    job_id VARCHAR(36),
                    name VARCHAR(1000),
                    rating VARCHAR(50),
                    review_count VARCHAR(100),
                    price_range VARCHAR(100),
                    category VARCHAR(500),
                    address VARCHAR(1000),
                    hours VARCHAR(1000),
                    phone VARCHAR(100),
                    website VARCHAR(1000),
                    services VARCHAR(1000),
                    price_per_person VARCHAR(100),
                    url VARCHAR(1000),
                    lat DOUBLE,
                    lng DOUBLE,
                    FOREIGN KEY (job_id) REFERENCES jobs(id)
                )
            """)
        conn.commit()
    finally:
        conn.close()


def create_job(job_id: str, search_query: str, country: str, city: str, street: str) -> dict:
    conn = get_connection()
    try:
        created_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO jobs (id, search_query, country, city, street, status, total_found, scraped_count, created_at)
                VALUES (%s, %s, %s, %s, %s, 'pending', 0, 0, %s)
                """,
                (job_id, search_query, country, city, street, created_at),
            )
            conn.commit()
            cur.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
            row = cur.fetchone()
            return _fmt_row(row)
    finally:
        conn.close()


def get_job(job_id: str) -> Optional[dict]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
            row = cur.fetchone()
            return _fmt_row(row)
    finally:
        conn.close()


def list_jobs() -> List[dict]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM jobs ORDER BY created_at DESC")
            rows = cur.fetchall()
            return [_fmt_row(r) for r in rows]
    finally:
        conn.close()


def search_jobs(country: str = "", city: str = "", street: str = "") -> List[dict]:
    """Return completed jobs matching the given country/city/street (fuzzy)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM jobs
                WHERE status = 'completed'
                  AND country LIKE %s
                  AND city LIKE %s
                  AND street LIKE %s
                ORDER BY created_at DESC
                """,
                (f"%{country}%", f"%{city}%", f"%{street}%"),
            )
            rows = cur.fetchall()
            return [_fmt_row(r) for r in rows]
    finally:
        conn.close()


def update_job_status(
    job_id: str,
    status: str,
    total_found: Optional[int] = None,
    scraped_count: Optional[int] = None,
    error_message: Optional[str] = None,
):
    conn = get_connection()
    try:
        sets = ["status = %s"]
        params = [status]
        if total_found is not None:
            sets.append("total_found = %s")
            params.append(total_found)
        if scraped_count is not None:
            sets.append("scraped_count = %s")
            params.append(scraped_count)
        if error_message is not None:
            sets.append("error_message = %s")
            params.append(error_message)
        if status in ("completed", "failed"):
            sets.append("completed_at = %s")
            params.append(datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
        params.append(job_id)
        with conn.cursor() as cur:
            cur.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = %s", params)
        conn.commit()
    finally:
        conn.close()


def insert_result(job_id: str, data: dict):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO results (
                    job_id, name, rating, review_count, price_range, category,
                    address, hours, phone, website, services, price_per_person, url, lat, lng
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    job_id,
                    data.get("name", ""),
                    data.get("rating", ""),
                    data.get("review_count", ""),
                    data.get("price_range", ""),
                    data.get("category", ""),
                    data.get("address", ""),
                    data.get("hours", ""),
                    data.get("phone", ""),
                    data.get("website", ""),
                    data.get("services", ""),
                    data.get("price_per_person", ""),
                    data.get("url", ""),
                    data.get("lat"),
                    data.get("lng"),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def get_results(job_id: str) -> List[dict]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM results WHERE job_id = %s ORDER BY id ASC", (job_id,)
            )
            rows = cur.fetchall()
            return [dict(r) for r in rows]
    finally:
        conn.close()
