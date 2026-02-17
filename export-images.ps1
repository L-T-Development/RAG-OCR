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
# RAG-OCR Offline Package - Enhanced NotebookLM-Style Edition

## 🎯 What's New in This Version
- ✨ NotebookLM-style suggested follow-up questions
- 🔍 Multi-document comparison with balanced retrieval
- 📊 Table content extraction and semantic search
- 💬 Conversation history support (last 5 messages)
- ⏱️ Unlimited processing time for large files
- 🎨 Enhanced UI with @ mention for document selection
- 📈 Adaptive query complexity detection (50+ chunks for complex queries)
- 🤖 GPU acceleration support for Ollama (CUDA)

## Contents
- backend-image.tar (~3.5GB) - Django backend with enhanced RAG engine
- frontend-image.tar (~22MB) - React app with NotebookLM features
- nginx-base.tar (~23MB) - Nginx base image
- docker-compose.yml - Docker configuration
- install.ps1 - Installation script

## System Capabilities
**Document Processing:**
- PDF, Excel (.xlsx, .xls), Word (.docx) support
- Table extraction with multi-page continuation detection
- OCR for images embedded in documents
- Automatic chunking and embedding (50 candidates, 30-50 final chunks)

**Intelligent Search:**
- Semantic search across all documents
- Multi-file comparison (@file1.pdf with @file2.pdf)
- Table data in ChromaDB for comprehensive search
- Balanced retrieval: minimum 3 chunks per mentioned file
- Conversation continuity for follow-up questions

**Query Features:**
- General questions answered from uploaded documents
- Exact part/drawing number searches
- Table data extraction and listing
- Document summarization (5-15 minute processing time)
- Suggested follow-up questions after each answer

**Processing Timeouts (No Artificial Limits):**
- Small documents (<100 pages): Up to 5 minutes
- Medium documents (100-500 pages): Up to 10 minutes  
- Large documents (500+ pages): Up to 15 minutes
- System displays: "⏱️ Estimated time: X minutes - processing will complete, please wait..."

## Install Instructions

### 1. Prerequisites
**Required:**
- Docker Desktop (latest version)
  Download: https://www.docker.com/products/docker-desktop

**For GPU Acceleration (Optional but Recommended):**
- NVIDIA GPU with CUDA support
- NVIDIA Container Toolkit installed

### 2. Load Images
Run the installation script:
``````powershell
.\install.ps1
``````

### 3. Setup Ollama (Required)

**Install Ollama:**
- Download: https://ollama.com/download
- Install and run: ``````ollama serve``````

**Pull Required Models:**
``````bash
# Embedding model (REQUIRED - 274MB)
ollama pull nomic-embed-text

# LLM model (REQUIRED - 4.9GB)
ollama pull llama3.1:8b
``````

**For GPU Acceleration:**
Ensure Ollama detects your NVIDIA GPU:
``````bash
docker run --gpus all --name ollama-gpu -d -v ollama:/root/.ollama -p 11434:11434 ollama/ollama
docker exec -it ollama-gpu ollama pull nomic-embed-text
docker exec -it ollama-gpu ollama pull llama3.1:8b
``````

### 4. Start Services
``````powershell
docker-compose up -d
``````

### 5. Verify Installation
- Frontend: http://localhost
- Backend API: http://localhost:8000
- Ollama: http://localhost:11434

**Check GPU usage (if enabled):**
``````bash
docker exec -it ollama-gpu nvidia-smi
``````

## Usage Guide

### Basic Workflow
1. **Upload Documents** - PDF, Excel, Word files
2. **Ask Questions** - Natural language queries
3. **Get Answers** - Grounded in your documents with sources
4. **Follow Suggested Questions** - Click to explore related topics

### Advanced Features

**@ Mention for File-Specific Queries:**
``````
summarize @document.pdf
compare @file1.pdf with @file2.pdf
what are the specs mentioned in @manual.pdf?
``````

**Multi-Document Comparison:**
System automatically:
- Retrieves content from ALL mentioned files (min 3 chunks each)
- Organizes context by document
- Provides structured comparison: Introduction → Similarities → Differences → Findings

**Table Queries:**
``````
list all part numbers
find drawing number ABC-12345
show all sr. numbers in the table
``````

**Follow-up Questions:**
Ask naturally - system remembers context:
``````
User: "What are the cancellation charges?"
AI: [Provides answer with 3 suggested questions]
User: "What about refunds?" (system understands context)
``````

## Architecture

**Backend Stack:**
- Django REST Framework
- ChromaDB (vector database)
- Ollama (LLM + embeddings)
- PyMuPDF, openpyxl, python-docx
- SQLite (tables database)

**Frontend Stack:**
- React + Vite
- React Markdown
- Lucide Icons
- CSS custom properties (theming)

**RAG Configuration:**
- Candidate retrieval: 50 chunks
- Final context: 30-50 chunks (adaptive)
- Distance filtering: 50-70% relative margin
- Context window: 16K tokens
- LLM temperature: 0.1-0.2 (factual answers)

## Troubleshooting

**GPU Not Detected:**
``````bash
docker run --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi
``````

**Ollama Connection Failed:**
Check Ollama is running: ``````curl http://localhost:11434``````

**Large File Processing:**
System will display estimated time. Be patient - no artificial limits!

**@ Mention Not Working:**
- Type ``````@``` followed by filename
- Select from dropdown (appears above input)
- Press Enter or click to select

## Performance Tips

1. **Use GPU**: 10-100x faster embeddings
2. **Pre-pull Models**: Pull llama3.1:8b before uploading documents
3. **Batch Upload**: Upload related documents in same thread
4. **Use @ Mentions**: Faster than full-thread search

## System Requirements

**Minimum:**
- 8GB RAM
- 20GB disk space
- 2 CPU cores

**Recommended:**
- 16GB RAM
- NVIDIA GPU with 6GB+ VRAM
- 50GB disk space
- 4+ CPU cores

## Support & Documentation

For detailed documentation, see:
- Backend: /backend/README.md
- Frontend: /frontend/README.md
- RAG Engine: /backend/process/rag_engine.py

## Version Info
Package Date: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
Features: NotebookLM-style suggestions, Multi-file comparison, Table extraction, Unlimited processing time
"@
$readme | Out-File "$packageDir\README.md" -Encoding UTF8

# Show summary
$totalSize = (Get-ChildItem -Path $packageDir -Recurse | Measure-Object -Property Length -Sum).Sum
$sizeGB = [math]::Round($totalSize / 1GB, 2)

Write-Host "=== Export Complete ===" -ForegroundColor Green
Write-Host "Location: $packageDir" -ForegroundColor Cyan
Write-Host "Size: $sizeGB GB" -ForegroundColor Cyan
