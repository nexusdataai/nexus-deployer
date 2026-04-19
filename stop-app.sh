#!/bin/bash

# Totogi Installer - Stop Script
# This script stops all running services

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}========================================"
echo -e "  Totogi Installer - Stopping Services"
echo -e "========================================${NC}"
echo ""

# Function to kill process on port
kill_port() {
    local port=$1
    local name=$2
    
    echo -e "${YELLOW}Stopping $name on port $port...${NC}"
    
    local pid=$(lsof -ti:$port 2>/dev/null)
    
    if [ ! -z "$pid" ]; then
        echo -e "  Killing process (PID: $pid)"
        kill -9 $pid 2>/dev/null || true
        echo -e "  ${GREEN}$name stopped${NC}"
    else
        echo -e "  No $name process found"
    fi
}

# Stop backend
kill_port 8001 "Backend"

# Stop frontend
kill_port 5173 "Frontend"

# Stop processes from PID files if they exist
if [ -f "backend.pid" ]; then
    echo ""
    echo -e "${YELLOW}Stopping backend from PID file...${NC}"
    BACKEND_PID=$(cat backend.pid)
    if ps -p $BACKEND_PID > /dev/null 2>&1; then
        kill -9 $BACKEND_PID 2>/dev/null || true
        echo -e "  ${GREEN}Backend stopped (PID: $BACKEND_PID)${NC}"
    fi
    rm -f backend.pid
fi

if [ -f "frontend.pid" ]; then
    echo -e "${YELLOW}Stopping frontend from PID file...${NC}"
    FRONTEND_PID=$(cat frontend.pid)
    if ps -p $FRONTEND_PID > /dev/null 2>&1; then
        kill -9 $FRONTEND_PID 2>/dev/null || true
        echo -e "  ${GREEN}Frontend stopped (PID: $FRONTEND_PID)${NC}"
    fi
    rm -f frontend.pid
fi

if [ -f "electron.pid" ]; then
    echo -e "${YELLOW}Stopping Electron from PID file...${NC}"
    ELECTRON_PID=$(cat electron.pid)
    if ps -p $ELECTRON_PID > /dev/null 2>&1; then
        kill -9 $ELECTRON_PID 2>/dev/null || true
        echo -e "  ${GREEN}Electron stopped (PID: $ELECTRON_PID)${NC}"
    fi
    rm -f electron.pid
fi

# Clean up log files
if [ -f "backend.log" ] || [ -f "frontend.log" ] || [ -f "electron.log" ]; then
    echo ""
    echo -e "${YELLOW}Cleaning up log files...${NC}"
    rm -f backend.log frontend.log electron.log
    echo -e "  ${GREEN}Log files removed${NC}"
fi

echo ""
echo -e "${GREEN}========================================"
echo -e "  All services stopped"
echo -e "========================================${NC}"
echo ""
