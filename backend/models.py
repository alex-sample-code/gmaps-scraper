from pydantic import BaseModel
from typing import Optional, List


class ScrapeRequest(BaseModel):
    country: str
    city: str
    street: str
    max_results: int = 50


class ScrapeResponse(BaseModel):
    job_id: str
    status: str
    search_query: str


class RestaurantResult(BaseModel):
    name: str
    rating: str
    review_count: str
    price_range: str
    category: str
    address: str
    hours: str
    phone: str
    website: str
    services: str
    price_per_person: str
    url: str
    lat: Optional[float] = None
    lng: Optional[float] = None


class JobSummary(BaseModel):
    id: str
    search_query: str
    status: str
    total_found: int
    scraped: int
    created_at: str


class JobDetail(BaseModel):
    id: str
    status: str
    search_query: str
    country: str
    city: str
    street: str
    total_found: int
    scraped: int
    error_message: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None
    results: List[RestaurantResult]
