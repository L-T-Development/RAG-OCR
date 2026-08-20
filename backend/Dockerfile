FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System deps: build tools + libs needed by PyMuPDF, onnxruntime, chromadb, pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    build-essential \
    git \
    libffi-dev \
    libssl-dev \
    libglib2.0-0 \
    libgomp1 \
    libgl1 \
    curl \
    default-jre-headless \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies from backend-specific requirements
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip && \
    pip install -r /tmp/requirements.txt

# Copy backend application
COPY backend/ /app/

# Create data directories (volumes will be mounted here)
RUN mkdir -p /app/pdfs /app/local_chroma_db /app/media /app/data

# Entrypoint: symlink sqlite to persistent volume, migrate, start gunicorn
#
# ONE worker process, many threads — deliberately. Ingestion, report and diff
# jobs live in in-process dicts and daemon threads, and the BM25 index is a
# module-level singleton loaded once per process. With 2+ workers a status poll
# that lands on the other worker 404s, keyword search goes stale for documents
# ingested by the other worker, and --max-requests recycling kills a long
# ingestion mid-run. Threads (gthread) keep the polling UI responsive while a
# long request runs; --max-requests is intentionally absent.
RUN printf '#!/bin/sh\n\
set -e\n\
if [ -f /app/db.sqlite3 ] && [ ! -L /app/db.sqlite3 ]; then\n\
    mv /app/db.sqlite3 /app/data/db.sqlite3\n\
fi\n\
if [ ! -f /app/data/db.sqlite3 ]; then\n\
    touch /app/data/db.sqlite3\n\
fi\n\
ln -sf /app/data/db.sqlite3 /app/db.sqlite3\n\
python manage.py migrate --noinput\n\
exec gunicorn ragocr.wsgi:application \\\n\
    --bind 0.0.0.0:8000 \\\n\
    --workers 1 \\\n\
    --threads 8 \\\n\
    --timeout 300\n\
' > /app/entrypoint.sh && chmod +x /app/entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/api/model/status/ || exit 1

CMD ["/app/entrypoint.sh"]
