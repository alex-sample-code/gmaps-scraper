FROM mcr.microsoft.com/playwright/python:v1.52.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

COPY backend/ backend/
COPY frontend/ frontend/
COPY scraper.py scraper.py

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
