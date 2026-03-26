FROM mcr.microsoft.com/playwright/python:v1.52.0-jammy

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium for Playwright
RUN playwright install chromium

COPY scraper.py .

# Output to /app/output so we can inspect results
RUN mkdir -p /app/output /app/screenshots
ENV OUTPUT_DIR=/app/output

CMD ["python", "scraper.py"]
