#!/bin/bash

# Build and run the Python MCP Docker container
# This script provides an easy way to build and run the containerized application

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Python MCP Docker Build and Run Script${NC}"
echo "=========================================="

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}Warning: .env file not found!${NC}"
    echo "Creating .env file from .env.example..."
    cp .env.example .env
    echo -e "${YELLOW}Please edit .env file with your actual configuration before running the container.${NC}"
    exit 1
fi

# Build the Docker image
echo -e "${BLUE}Building Docker image...${NC}"
docker build -t python-mcp:latest .

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Docker image built successfully!${NC}"
else
    echo -e "${RED}❌ Failed to build Docker image${NC}"
    exit 1
fi

# Ask user if they want to run the container
echo -e "${YELLOW}Do you want to run the container now? (y/n)${NC}"
read -r response

if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
    echo -e "${BLUE}Starting container...${NC}"
    
    # Check if docker-compose is available
    if command -v docker-compose &> /dev/null || command -v docker compose &> /dev/null; then
        echo "Using docker-compose..."
        if command -v docker-compose &> /dev/null; then
            docker-compose up -d
        else
            docker compose up -d
        fi
    else
        echo "Using docker run..."
        docker run -d \
            --name python-mcp-container \
            -p 8000:8000 \
            --env-file .env \
            python-mcp:latest
    fi
    
    echo -e "${GREEN}✅ Container started successfully!${NC}"
    echo -e "${BLUE}📋 Access the application at: http://localhost:8000${NC}"
    echo -e "${BLUE}📖 API Documentation at: http://localhost:8000/docs${NC}"
    echo -e "${BLUE}🔍 Health check at: http://localhost:8000/docs/allowed-libraries-versions${NC}"
else
    echo -e "${YELLOW}Container build complete. Run manually when ready.${NC}"
fi

echo -e "${GREEN}🎉 Setup complete!${NC}"
