FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=7860

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /usr/sbin/nologin appuser

COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && pip install -r requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/
COPY data/curated_visit_profiles.json data/curated_visit_profiles.json
COPY data/demo_pois.json data/demo_pois.json
COPY data/destination_knowledge.json data/destination_knowledge.json
COPY data/guide_visit_standards.md data/guide_visit_standards.md
COPY data/tengwang_candidates.png data/tengwang_candidates.png
COPY data/tengwang_west_candidates.png data/tengwang_west_candidates.png

RUN mkdir -p /app/data/runtime /app/data/reports \
    && touch /app/.env \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,sys,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"7860\")}/health', timeout=3); sys.exit(0)"

CMD ["sh", "-c", "uvicorn backend.main:application --host 0.0.0.0 --port ${PORT:-7860}"]
