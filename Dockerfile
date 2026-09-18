# syntax=docker/dockerfile:1

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    CACHE_DIR=/data/cache \
    CACHE_BACKEND=file

WORKDIR /app

# Install dependencies first
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY ai/ ./ai/
COPY researcher/ ./researcher/
COPY backend/ ./backend/
COPY data/ ./data/

# Create non-root user and writable cache directory
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /data/cache \
    && chown -R appuser:appuser /app /data

USER appuser

VOLUME ["/data/cache"]

# Verify imports during build
RUN python -c "import researcher, ai, backend.api; print('imports ok')"

EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn backend.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
