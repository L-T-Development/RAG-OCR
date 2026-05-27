#!/bin/bash
# Docker Offline Export Script (Linux/Mac)
# This script exports all RAG-OCR Docker images and creates an offline installation package

echo "=== RAG-OCR Docker Offline Export ==="
echo ""

# Create export directory
EXPORT_DIR="./docker-offline-package"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
PACKAGE_NAME="ragocr-docker-$TIMESTAMP"
PACKAGE_DIR="$EXPORT_DIR/$PACKAGE_NAME"

echo "Creating export directory: $PACKAGE_DIR"
mkdir -p "$PACKAGE_DIR"

# Build the images first
echo ""
echo "Building Docker images..."
docker compose build

# Export backend image
echo ""
echo "Exporting backend image..."
docker save rag-ocr-backend:latest -o "$PACKAGE_DIR/backend-image.tar"
echo "✓ Backend image saved: backend-image.tar"

# Export frontend image
echo ""
echo "Exporting frontend image..."
docker save rag-ocr-frontend:latest -o "$PACKAGE_DIR/frontend-image.tar"
echo "✓ Frontend image saved: frontend-image.tar"

# Export base images
echo ""
echo "Exporting base images..."

docker pull python:3.12-slim
docker save python:3.12-slim -o "$PACKAGE_DIR/python-base.tar"
echo "✓ Python base image saved"

docker pull node:20-alpine
docker save node:20-alpine -o "$PACKAGE_DIR/node-base.tar"
echo "✓ Node base image saved"

docker pull nginx:alpine
docker save nginx:alpine -o "$PACKAGE_DIR/nginx-base.tar"
echo "✓ Nginx base image saved"

# Copy configuration files
echo ""
echo "Copying configuration files..."
cp docker-compose.yml "$PACKAGE_DIR/"
cp DOCKER_DEPLOYMENT.md "$PACKAGE_DIR/"
cp .dockerignore "$PACKAGE_DIR/" 2>/dev/null || true
cp backend/.dockerignore "$PACKAGE_DIR/backend.dockerignore" 2>/dev/null || true
cp frontend/.dockerignore "$PACKAGE_DIR/frontend.dockerignore" 2>/dev/null || true

# Create installation script
echo ""
echo "Creating installation script..."
cat > "$PACKAGE_DIR/install.sh" << 'EOF'
#!/bin/bash
# RAG-OCR Offline Installation Script
# Run this on the target offline machine

echo "=== RAG-OCR Offline Installation ==="
echo ""

# Check Docker is installed
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker is not installed!"
    echo "Please install Docker first: https://docs.docker.com/engine/install/"
    exit 1
fi

# Check Docker is running
if ! docker info &> /dev/null; then
    echo "ERROR: Docker is not running!"
    echo "Please start Docker and try again."
    exit 1
fi

echo "✓ Docker is installed and running"
echo ""

# Load base images
echo "Loading base images..."
docker load -i python-base.tar
docker load -i node-base.tar
docker load -i nginx-base.tar
echo "✓ Base images loaded"
echo ""

# Load application images
echo "Loading RAG-OCR images..."
docker load -i backend-image.tar
docker load -i frontend-image.tar
echo "✓ Application images loaded"
echo ""

# Verify images
echo "Verifying loaded images..."
docker images | grep rag-ocr
echo ""

echo "=== Installation Complete ==="
echo ""
echo "Next steps:"
echo "1. Make sure Ollama is installed and running on this machine"
echo "   Download: https://ollama.com/download"
echo "2. Pull the embedding model:"
echo "   ollama pull nomic-embed-text"
echo "3. Start the application:"
echo "   docker compose up -d"
echo "4. Access the application:"
echo "   Frontend: http://localhost"
echo "   Backend:  http://localhost:8000"
echo ""
EOF

chmod +x "$PACKAGE_DIR/install.sh"

# Create README (same as PowerShell version)
cat > "$PACKAGE_DIR/README.md" << EOF
# RAG-OCR Offline Installation Package

This package contains all Docker images needed to run RAG-OCR offline.

## Package Contents

- \`backend-image.tar\` - Django backend image
- \`frontend-image.tar\` - React frontend with Nginx
- \`python-base.tar\` - Python 3.12 base image
- \`node-base.tar\` - Node 20 base image
- \`nginx-base.tar\` - Nginx Alpine base image
- \`docker-compose.yml\` - Docker Compose configuration
- \`install.sh\` - Automated installation script (Linux/Mac)
- \`DOCKER_DEPLOYMENT.md\` - Detailed deployment guide

## Prerequisites

1. **Docker** + **Docker Compose**
   - Installation: https://docs.docker.com/engine/install/

2. **Ollama** (for embeddings)
   - Download: https://ollama.com/download
   - Install and run: \`ollama serve\`
   - Pull model: \`ollama pull nomic-embed-text\`

## Quick Installation

### Option 1: Automated

\`\`\`bash
# Run the installation script
chmod +x install.sh
./install.sh
\`\`\`

### Option 2: Manual

\`\`\`bash
# 1. Load base images
docker load -i python-base.tar
docker load -i node-base.tar
docker load -i nginx-base.tar

# 2. Load application images
docker load -i backend-image.tar
docker load -i frontend-image.tar

# 3. Verify images loaded
docker images | grep rag-ocr

# 4. Start the application
docker compose up -d
\`\`\`

## Post-Installation

1. **Verify containers are running:**
   \`\`\`bash
   docker compose ps
   \`\`\`

2. **Check logs if needed:**
   \`\`\`bash
   docker compose logs backend
   docker compose logs frontend
   \`\`\`

3. **Access the application:**
   - Frontend: http://localhost
   - Backend API: http://localhost:8000/api/
   - Ollama: http://localhost:11434

## System Requirements

- **OS**: Windows 10/11, macOS 10.15+, or Linux
- **RAM**: 4GB minimum, 8GB recommended
- **Disk**: 10GB free space
- **CPU**: 2+ cores recommended

## Package Info

- Generated: $TIMESTAMP
- Version: RAG-OCR Docker Package
- Images: 5 (2 application + 3 base)
EOF

# Calculate package size
echo ""
echo "Calculating package size..."
TOTAL_SIZE=$(du -sh "$PACKAGE_DIR" | cut -f1)
echo "Total package size: $TOTAL_SIZE"
echo ""

echo "Package created successfully!"
echo ""
echo "Package location: $PACKAGE_DIR"
echo ""
echo "Next steps:"
echo "1. Transfer the '$PACKAGE_NAME' folder to your offline machine"
echo "2. On the offline machine, run: ./install.sh"
echo "3. Make sure Ollama is installed with nomic-embed-text model"
echo ""
echo "Optional: Create a compressed archive for easier transfer:"
echo "tar -czf $EXPORT_DIR/$PACKAGE_NAME.tar.gz -C $EXPORT_DIR $PACKAGE_NAME"
echo ""
