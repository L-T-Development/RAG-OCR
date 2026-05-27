# Docker Offline Export Script
# This script exports all RAG-OCR Docker images and creates an offline installation package

Write-Host "=== RAG-OCR Docker Offline Export ===" -ForegroundColor Cyan
Write-Host ""

# Create export directory
$exportDir = ".\docker-offline-package"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$packageName = "ragocr-docker-$timestamp"
$packageDir = "$exportDir\$packageName"

Write-Host "Creating export directory: $packageDir" -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path $packageDir | Out-Null

# Build the images first
Write-Host "`nBuilding Docker images..." -ForegroundColor Yellow
docker compose build

# Export backend image
Write-Host "`nExporting backend image..." -ForegroundColor Yellow
docker save rag-ocr-backend:latest -o "$packageDir\backend-image.tar"
Write-Host "✓ Backend image saved: backend-image.tar" -ForegroundColor Green

# Export frontend image
Write-Host "`nExporting frontend image..." -ForegroundColor Yellow
docker save rag-ocr-frontend:latest -o "$packageDir\frontend-image.tar"
Write-Host "✓ Frontend image saved: frontend-image.tar" -ForegroundColor Green

# Export base images (needed for building)
Write-Host "`nExporting base images..." -ForegroundColor Yellow

# Python base image
docker pull python:3.12-slim
docker save python:3.12-slim -o "$packageDir\python-base.tar"
Write-Host "✓ Python base image saved" -ForegroundColor Green

# Node base image
docker pull node:20-alpine
docker save node:20-alpine -o "$packageDir\node-base.tar"
Write-Host "✓ Node base image saved" -ForegroundColor Green

# Nginx base image
docker pull nginx:alpine
docker save nginx:alpine -o "$packageDir\nginx-base.tar"
Write-Host "✓ Nginx base image saved" -ForegroundColor Green

# Copy configuration files
Write-Host "`nCopying configuration files..." -ForegroundColor Yellow
Copy-Item "docker compose.yml" "$packageDir\"
Copy-Item "DOCKER_DEPLOYMENT.md" "$packageDir\"
Copy-Item ".dockerignore" "$packageDir\" -ErrorAction SilentlyContinue
Copy-Item "backend\.dockerignore" "$packageDir\backend.dockerignore" -ErrorAction SilentlyContinue
Copy-Item "frontend\.dockerignore" "$packageDir\frontend.dockerignore" -ErrorAction SilentlyContinue

# Create installation script
Write-Host "`nCreating installation script..." -ForegroundColor Yellow
$installScript = @'
# RAG-OCR Offline Installation Script
# Run this on the target offline machine

Write-Host "=== RAG-OCR Offline Installation ===" -ForegroundColor Cyan
Write-Host ""

# Check Docker is installed
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Docker is not installed!" -ForegroundColor Red
    Write-Host "Please install Docker Desktop first: https://www.docker.com/products/docker-desktop" -ForegroundColor Yellow
    exit 1
}

# Check Docker is running
$dockerStatus = docker info 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Docker is not running!" -ForegroundColor Red
    Write-Host "Please start Docker Desktop and try again." -ForegroundColor Yellow
    exit 1
}

Write-Host "✓ Docker is installed and running" -ForegroundColor Green
Write-Host ""

# Load base images
Write-Host "Loading base images..." -ForegroundColor Yellow
docker load -i python-base.tar
docker load -i node-base.tar
docker load -i nginx-base.tar
Write-Host "✓ Base images loaded" -ForegroundColor Green
Write-Host ""

# Load application images
Write-Host "Loading RAG-OCR images..." -ForegroundColor Yellow
docker load -i backend-image.tar
docker load -i frontend-image.tar
Write-Host "✓ Application images loaded" -ForegroundColor Green
Write-Host ""

# Verify images
Write-Host "Verifying loaded images..." -ForegroundColor Yellow
docker images | Select-String "rag-ocr"
Write-Host ""

Write-Host "=== Installation Complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. Make sure Ollama is installed and running on this machine" -ForegroundColor White
Write-Host "   Download: https://ollama.com/download" -ForegroundColor Gray
Write-Host "2. Pull the embedding model:" -ForegroundColor White
Write-Host "   ollama pull nomic-embed-text" -ForegroundColor Gray
Write-Host "3. Start the application:" -ForegroundColor White
Write-Host "   docker compose up -d" -ForegroundColor Gray
Write-Host "4. Access the application:" -ForegroundColor White
Write-Host "   Frontend: http://localhost" -ForegroundColor Gray
Write-Host "   Backend:  http://localhost:8000" -ForegroundColor Gray
Write-Host ""
'@

$installScript | Out-File -FilePath "$packageDir\install.ps1" -Encoding UTF8

# Create README
Write-Host "Creating README..." -ForegroundColor Yellow
@"
# RAG-OCR Offline Installation Package

This package contains all Docker images needed to run RAG-OCR offline.

## Package Contents

* backend-image.tar - Django backend image
* frontend-image.tar - React frontend with Nginx
* python-base.tar - Python 3.12 base image
* node-base.tar - Node 20 base image
* nginx-base.tar - Nginx Alpine base image
* docker compose.yml - Docker Compose configuration
* install.ps1 - Automated installation script
* DOCKER_DEPLOYMENT.md - Detailed deployment guide

## Prerequisites

1. Docker Desktop (or Docker Engine + Docker Compose)
   * Windows/Mac: https://www.docker.com/products/docker-desktop
   * Linux: https://docs.docker.com/engine/install/

2. Ollama (for embeddings - must be installed separately on host)
   * Download: https://ollama.com/download
   * Install and run: ollama serve
   * Pull model: ollama pull nomic-embed-text

## Quick Installation

### Option 1: Automated (PowerShell)

Run the install.ps1 script in PowerShell.

### Option 2: Manual

Load base images:
  docker load -i python-base.tar
  docker load -i node-base.tar
  docker load -i nginx-base.tar

Load application images:
  docker load -i backend-image.tar
  docker load -i frontend-image.tar

Verify images loaded:
  docker images | findstr rag-ocr

Start the application:
  docker compose up -d

## Post-Installation

1. Verify containers are running: docker compose ps
2. Check logs if needed: docker compose logs backend
3. Access the application:
   * Frontend: http://localhost
   * Backend API: http://localhost:8000/api/
   * Ollama: http://localhost:11434

## Troubleshooting

See DOCKER_DEPLOYMENT.md for detailed troubleshooting steps.

## System Requirements

* OS: Windows 10/11, macOS 10.15+, or Linux
* RAM: 4GB minimum, 8GB recommended
* Disk: 10GB free space
* CPU: 2+ cores recommended

## Package Info

* Version: RAG-OCR Docker Package
* Images: 5 (2 application + 3 base)
"@ | Out-File -FilePath "$packageDir\README.md" -Encoding UTF8

# Calculate package size
Write-Host "`nCalculating package size..." -ForegroundColor Yellow
$totalSize = (Get-ChildItem -Path $packageDir -Recurse | Measure-Object -Property Length -Sum).Sum
$sizeGB = [math]::Round($totalSize / 1GB, 2)
Write-Host "Total package size: $sizeGB GB" -ForegroundColor Cyan
Write-Host ""

# Create archive (optional - can be large)
Write-Host "Package created successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "Package location: $packageDir" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Transfer the package folder to your offline machine" -ForegroundColor White
Write-Host "2. On the offline machine, run: .\install.ps1" -ForegroundColor White
Write-Host "3. Make sure Ollama is installed with nomic-embed-text model" -ForegroundColor White
Write-Host ""
Write-Host "Optional: Create a compressed archive for easier transfer:" -ForegroundColor Yellow
Write-Host "  Compress-Archive -Path `"$packageDir`" -DestinationPath `"$exportDir\$packageName.zip`"" -ForegroundColor Gray
Write-Host ""
