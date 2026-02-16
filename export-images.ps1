# Export RAG-OCR Docker Images for Offline Installation

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$packageDir = "docker-offline-package\ragocr-docker-$timestamp"
New-Item -ItemType Directory -Path $packageDir -Force | Out-Null

Write-Host "=== Exporting RAG-OCR Docker Images ===" -ForegroundColor Cyan
Write-Host "Output: $packageDir" -ForegroundColor Yellow
Write-Host ""

# Build images
Write-Host "Building images..." -ForegroundColor Yellow
docker-compose build
Write-Host "Build complete" -ForegroundColor Green
Write-Host ""

# Save images
Write-Host "Saving images to tar files..." -ForegroundColor Yellow

docker save rag-ocr-backend:latest -o "$packageDir\backend-image.tar"
Write-Host "  backend-image.tar" -ForegroundColor Gray

docker save rag-ocr-frontend:latest -o "$packageDir\frontend-image.tar"
Write-Host "  frontend-image.tar" -ForegroundColor Gray

docker save nginx:alpine -o "$packageDir\nginx-base.tar"
Write-Host "  nginx-base.tar" -ForegroundColor Gray

Write-Host "Images saved" -ForegroundColor Green
Write-Host ""

# Copy files
Copy-Item "docker-compose.yml" "$packageDir\"
Copy-Item "DOCKER_DEPLOYMENT.md" "$packageDir\" -ErrorAction SilentlyContinue

# Create install script
$install = @"
Write-Host 'Loading Docker images...' -ForegroundColor Yellow
docker load -i nginx-base.tar
docker load -i backend-image.tar
docker load -i frontend-image.tar
Write-Host 'Images loaded. Run: docker-compose up -d' -ForegroundColor Green
"@
$install | Out-File "$packageDir\install.ps1" -Encoding UTF8

# Create README
$readme = @"
# RAG-OCR Offline Package

## Contents
- backend-image.tar (3.5GB) - Django backend with Python
- frontend-image.tar (22MB) - React app
- nginx-base.tar (23MB) - Nginx base image
- docker-compose.yml - Docker configuration
- install.ps1 - Installation script

## Install
1. Run: .\install.ps1
2. Run: docker-compose up -d
3. Access: http://localhost

## Prerequisites
- Docker Desktop installed and running
- Ollama installed with nomic-embed-text model
  Download: https://ollama.com/download
  Run: ollama serve
  Pull model: ollama pull nomic-embed-text
"@
$readme | Out-File "$packageDir\README.md" -Encoding UTF8

# Show summary
$totalSize = (Get-ChildItem -Path $packageDir -Recurse | Measure-Object -Property Length -Sum).Sum
$sizeGB = [math]::Round($totalSize / 1GB, 2)

Write-Host "=== Export Complete ===" -ForegroundColor Green
Write-Host "Location: $packageDir" -ForegroundColor Cyan
Write-Host "Size: $sizeGB GB" -ForegroundColor Cyan
