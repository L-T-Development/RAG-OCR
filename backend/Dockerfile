# Use Python 3.12 slim image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies  
COPY requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip && \
    pip install -r /tmp/requirements.txt

# Copy backend application
COPY backend/ /app/

# Create necessary directories for data persistence
RUN mkdir -p /app/pdfs /app/local_chroma_db /app/media /app/data

# Move db.sqlite3 to data directory if migrations create it in root
RUN echo "#!/bin/sh" > /app/entrypoint.sh && \
    echo "if [ -f /app/db.sqlite3 ]; then mv /app/db.sqlite3 /app/data/; fi" >> /app/entrypoint.sh && \
    echo "if [ ! -f /app/data/db.sqlite3 ]; then ln -s /app/data/db.sqlite3 /app/db.sqlite3 || true; else ln -sf /app/data/db.sqlite3 /app/db.sqlite3; fi" >> /app/entrypoint.sh && \
    echo "python manage.py migrate" >> /app/entrypoint.sh && \
    echo "exec python manage.py runserver 0.0.0.0:8000" >> /app/entrypoint.sh && \
    chmod +x /app/entrypoint.sh

# Expose Django port
EXPOSE 8000

# Run migrations and start server
CMD ["/app/entrypoint.sh"]
