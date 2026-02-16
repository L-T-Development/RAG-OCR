# Docker Deployment Guide

## Overview
This Docker setup runs the RAG-OCR application with:
- **Backend**: Django REST API (port 8000)
- **Frontend**: React + Vite with Nginx (port 80)
- **Ollama**: Uses your **existing local Ollama** installation (not containerized)

## Prerequisites
- Docker Engine 20.10+
- Docker Compose 2.0+
- **Ollama installed and running on host** with nomic-embed-text model
- At least 4GB RAM available
- 10GB disk space

## Quick Start

### 0. Ensure Ollama is Running
Make sure Ollama is running on your host machine:
```bash
# Verify Ollama is running
curl http://localhost:11434/api/tags

# If not running, start it
ollama serve

# Ensure you have the model
ollama pull nomic-embed-text
```

### 1. Build and Start All Services
```bash
docker-compose up --build
```

### 2. Access the Application
- **Frontend**: http://localhost
- **Backend API**: http://localhost:8000/api/
- **Ollama API**: http://localhost:11434

### 3. Stop Services
```bash
docker-compose down
```

## Detailed Commands

### Build Images Only
```bash
docker-compose build
```

### Start in Detached Mode (Background)
```bash
docker-compose up -d
```

### View Logs
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f backend
docker-compose logs -f ollama
docker-compose logs -f frontend
```

### Restart a Service
```bash
docker-compose restart backend
```

### Stop and Remove Volumes (Clean Start)
```bash
docker-compose down -v
```

## Service Details

### Backend Service
- **Image**: Custom Python 3.12 slim
- **Excludes**: sentence-transformers (using Ollama only)
- **Connects to**: Host Ollama via `host.docker.internal:11434`
- **Volumes**:
  - `backend_db`: SQLite database persistence
  - `backend_pdfs`: Uploaded PDF documents
  - `backend_chroma`: ChromaDB vector storage
  - `backend_media`: Media files

### Ollama (Host Installation)
- **Location**: Running on your host machine (not in Docker)
- **Port**: 11434 (must be accessible from Docker containers)
- **Model**: nomic-embed-text (must be pre-installed)
- **Connection**: Backend uses `host.docker.internal` to reach host Ollama

### Frontend Service
- **Image**: Multi-stage build (Node.js → Nginx)
- **Build**: Vite production build
- **Reverse Proxy**: Nginx routes `/api/*` to backend

## Configuration

### Environment Variables
Edit `docker-compose.yml` to customize:

```yaml
backend:
  environment:host.docker.internal:11434  # Host Ollama URL
    - DEBUG=False               BASE=http://ollama:11434  # Ollama service URL
    - DEBUG=False                          # Set to False for production
    - ALLOWED_HOSTS=localhost,yourdomain.com
```

### Port Mapping
Change external ports if needed:

```yaml
services:
  frontend:
    ports:
      - "8080:80"  # Access frontend on port 8080
  backend:
    ports:
      - "8001:8000"  # Access backend on port 8001
```

## Data Persistence

All data is stored in Docker volumes:

```bash
# List volumes
docker volume ls | grep ragocr

# Inspect a volume
docker volume inspect rag-ocr_backend_db

# Backup a volume
docker run --rm -v rag-ocr_backend_db:/data -v $(pwd):/backup alpine tar czf /backup/db-backup.tar.gz /data

# Restore a volume
docker run --rm -v rag-ocr_backend_db:/data -v $(pwd):/backup alpine tar xzf /backup/db-backup.tar.gz -C /
```

## Troubleshooting
Connection Issues
```bash
# Verify Ollama is running on host
curl http://localhost:11434/api/tags

# Check if model is available
ollama list | grep nomic-embed-text

# Test from within Docker container
docker-compose exec backend curl http://host.docker.internal:11434/api/tags

# If connection fails, ensure Ollama is listening on all interfaces
# Check Ollama configuration or restart with: ollama serve
```

### Backend Can't Reach Ollama
On **Linux**, you may need to use the host IP instead of `host.docker.internal`:
```yaml
# Find your host IP
ip addr show docker0

# Update docker-compose.yml:
environment:
  - OLLAMA_API_BASE=http://172.17.0.1:11434  # Use your docker0 IP
docker-compose exec ollama ollama list
```

### Backend Database Migrations
```bash
# Run migrations manually
docker-compose exec backend python manage.py migrate

# Create superuser
docker-compose exec backend python manage.py createsuperuser
```

### Frontend Build Errors
```bash
# Rebuild frontend only
docker-compose build frontend

# Check Node modules
docker-compose run --rm frontend npm install
```

### Permission Issues
```bash
# Fix volume permissions
docker-compose exec backend chown -R 1000:1000 /app/pdfs /app/local_chroma_db
```

### Container Won't Start
```bash
# Check container status
docker-compose ps

# View detailed logs
docker-compose logs --tail=100 backend

# Remove and recreate containers
docker-compose down
docker-compose up --force-recreate
```

## Development vs Production

### Development Mode (Current Setup)
- Django DEBUG=True
- Dev server (manage.py runserver)
- Hot reload (volume mounted)

### Production Recommendations
1. **Use Gunicorn instead of dev server**
   ```dockerfile
   # In backend/Dockerfile
   CMD ["gunicorn", "ragocr.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4"]
   ```

2. **Disable DEBUG**
   ```yaml
   # In docker-compose.yml
   environment:
     - DEBUG=False
   ```

3. **Use production database**
   - Replace SQLite with PostgreSQL
   - Add postgres service to docker-compose.yml

4. **Enable SSL**
   - Use Let's Encrypt with Certbot
   - Configure Nginx for HTTPS

5. **Add Redis for caching**
   ```yaml
   redis:
     image: redis:alpine
     ports:
       - "6379:6379"
   ```
# Update on host (not in Docker)
ollama pull nomic-embed-text:latest

## Updating the Application

### Update Backend Code
```bash
# Pull latest code
git pull

# Rebuild and restart
docker-compose up --build backend
```

### Update Ollama Model
```bash
# Update on host (not in Docker)
ollama pull nomic-embed-text:latest

# Then restart backend to reload
docker-compose restart backend
```

### Update Dependencies
```bash
# Rebuild with --no-cache
docker-compose build --no-cache backend
```

## Monitoring

### Resource Usage
```bash
docker stats
```

### Service Health
```bash
# Check Ollama health
curl http://localhost:11434/api/tags

# Check backend health
curl http://localhost:8000/api/model/status

# Check frontend
curl http://localhost
```

## Network Architecture

```
Internet / User Browser
   |
   v
Frontend (Nginx:80) -----> Backend (Django:8000) 
                                  |
                                  | (via host.docker.internal)
                                  v
                           Host Ollama (API:11434)
                                  |
                                  v
                           nomic-embed-text model
   
   Backend Internal:
   - ChromaDB (Embedded, 768-dim vectors)
   - SQLite Database (app data)
```

## Security Notes

1. **Change DEBUG to False in production**
2. **Set strong SECRET_KEY in Django settings**
3. **Configure ALLOWED_HOSTS properly**
4. **Use environment variables for secrets**
5. **Enable firewall rules**
6. **Regular security updates**: `docker-compose pull && docker-compose up -d`

## Backup Strategy

### Automated Backup Script
```bash
#!/bin/bash
BACKUP_DIR="./backups/$(date +%Y%m%d)"
mkdir -p $BACKUP_DIR

# Backup database
docker run --rm -v rag-ocr_backend_db:/data -v $(pwd)/$BACKUP_DIR:/backup alpine tar czf /backup/db.tar.gz /data

# Backup ChromaDB
docker run --rm -v rag-ocr_backend_chroma:/data -v $(pwd)/$BACKUP_DIR:/backup alpine tar czf /backup/chroma.tar.gz /data

# Backup PDFs
docker run --rm -v rag-ocr_backend_pdfs:/data -v $(pwd)/$BACKUP_DIR:/backup alpine tar czf /backup/pdfs.tar.gz /data

echo "Backup completed: $BACKUP_DIR"
```

## Support

For issues or questions:
1. Check logs: `docker-compose logs -f`
2. Review this documentation
3. Check Docker and system resources
4. Verify network connectivity between services

## Additional Resources

- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [Ollama Documentation](https://github.com/ollama/ollama)
- [Django Deployment Checklist](https://docs.djangoproject.com/en/stable/howto/deployment/checklist/)
- [Nginx Configuration Guide](https://nginx.org/en/docs/)
