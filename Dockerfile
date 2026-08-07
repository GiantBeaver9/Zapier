FROM python:3.12-slim

WORKDIR /srv

# Install deps first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY migrations ./migrations

EXPOSE 8000

# The app applies migrations (CREATE TABLE IF NOT EXISTS) and seeds the demo
# customers on startup, so `docker compose up` needs no init scripts.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
