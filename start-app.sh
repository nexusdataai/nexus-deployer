#!/bin/bash

# Totogi Installer - Smart Startup Script
# This script will:
# 1. Check and stop existing processes on ports 8001 and 5173
# 2. Start backend with venv
# 3. Wait for backend health check
# 4. Start frontend
# 5. Open browser

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}========================================"
echo -e "  Totogi Installer - Smart Startup"
echo -e "========================================${NC}"
echo ""

# Step 1: Check and stop existing processes
echo -e "${YELLOW}[1/6] Checking for existing processes...${NC}"

# Function to kill process on port
kill_port() {
    local port=$1
    local pid=$(lsof -ti:$port 2>/dev/null)
    
    if [ ! -z "$pid" ]; then
        echo -e "  ${RED}Stopping process on port $port (PID: $pid)${NC}"
        kill -9 $pid 2>/dev/null || true
        sleep 2
        echo -e "  ${GREEN}Port $port is now free${NC}"
    else
        echo -e "  ${GREEN}Port $port is free${NC}"
    fi
}

kill_port 8001
kill_port 5173
echo ""

# Step 2: Check Python venv
echo -e "${YELLOW}[2/6] Checking Python virtual environment...${NC}"

if [ ! -f "backend/venv/bin/python" ]; then
    echo -e "  ${RED}ERROR: Virtual environment not found!${NC}"
    echo -e "  ${RED}Please run: cd backend && python3 -m venv venv && venv/bin/pip install -r requirements.txt${NC}"
    exit 1
fi

echo -e "  ${GREEN}Virtual environment found${NC}"
echo ""

# Step 3: Start backend
echo -e "${YELLOW}[3/6] Starting backend server...${NC}"

cd backend
source venv/bin/activate

# Generate (or reuse) the loopback self-signed cert for HTTPS so the backend
# never serves cleartext (CWE-319). Cert lives under ~/.nexus/local-tls/.
TLS_PATHS=$(python -c "from app.utils.local_tls import ensure_local_tls; c,k,_=ensure_local_tls(); print(c); print(k)")
CERT_PATH=$(echo "$TLS_PATHS" | sed -n '1p')
KEY_PATH=$(echo "$TLS_PATHS" | sed -n '2p')

# Start backend in background (HTTPS on 127.0.0.1:8001)
nohup python -m uvicorn app.main:app \
    --host 127.0.0.1 --port 8001 --reload \
    --ssl-keyfile "$KEY_PATH" --ssl-certfile "$CERT_PATH" \
    > ../backend.log 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > ../backend.pid

cd ..
echo -e "  ${GREEN}Backend starting (PID: $BACKEND_PID)${NC}"
echo ""

# Step 4: Wait for backend health check
echo -e "${YELLOW}[4/6] Waiting for backend to be ready...${NC}"

MAX_ATTEMPTS=30
ATTEMPT=0
BACKEND_READY=false

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    ATTEMPT=$((ATTEMPT + 1))
    
    if curl -sk https://127.0.0.1:8001/api/health > /dev/null 2>&1; then
        BACKEND_READY=true
        echo -e "  ${GREEN}Backend is ready! (attempt $ATTEMPT/$MAX_ATTEMPTS)${NC}"
        break
    fi
    
    echo -e "  Attempt $ATTEMPT/$MAX_ATTEMPTS : Backend not ready yet..."
    sleep 1
done

if [ "$BACKEND_READY" = false ]; then
    echo -e "  ${RED}ERROR: Backend failed to start after 30 seconds${NC}"
    echo -e "  ${RED}Check backend.log for errors${NC}"
    cat backend.log
    exit 1
fi

echo ""

# Step 5: Start frontend
echo -e "${YELLOW}[5/6] Starting frontend server...${NC}"

cd frontend

# Start frontend in background
nohup npm run dev > ../frontend.log 2>&1 &
FRONTEND_PID=$!
echo $FRONTEND_PID > ../frontend.pid

cd ..
echo -e "  ${GREEN}Frontend starting (PID: $FRONTEND_PID)${NC}"
echo -e "  Waiting for frontend to initialize..."
sleep 5
echo ""

# Step 6: Start Electron desktop app
echo -e "${YELLOW}[6/7] Starting Electron desktop app...${NC}"

cd electron

if [ -d "node_modules" ]; then
    # Start Electron in background
    nohup npm run dev > ../electron.log 2>&1 &
    ELECTRON_PID=$!
    echo $ELECTRON_PID > ../electron.pid
    
    cd ..
    echo -e "  ${GREEN}Electron starting (PID: $ELECTRON_PID)${NC}"
    sleep 3
else
    cd ..
    echo -e "  ${YELLOW}Electron dependencies not found. Skipping desktop app.${NC}"
    echo -e "  To install: cd electron && npm install"
fi

echo ""

# Step 7: Open browser
echo -e "${YELLOW}[7/7] Opening application in browser...${NC}"

sleep 2

# Try to open browser (works on most systems)
if command -v xdg-open > /dev/null; then
    xdg-open http://localhost:5173 2>/dev/null &
elif command -v open > /dev/null; then
    open http://localhost:5173 2>/dev/null &
elif command -v start > /dev/null; then
    start http://localhost:5173 2>/dev/null &
fi

echo ""
echo -e "${GREEN}========================================"
echo -e "  Startup Complete!"
echo -e "========================================${NC}"
echo ""
echo -e "${CYAN}Backend:  https://127.0.0.1:8001${NC}"
echo -e "${CYAN}Frontend: http://localhost:5173${NC}"
echo -e "${CYAN}Desktop:  Electron app window${NC}"
echo ""
echo -e "The application is running in the background."
echo -e "Logs are available in:"
echo -e "  - backend.log"
echo -e "  - frontend.log"
echo -e "  - electron.log"
echo ""
echo -e "${YELLOW}To stop all services, run: ./stop-app.sh${NC}"
echo ""
echo -e "Process IDs saved to:"
echo -e "  - backend.pid (PID: $BACKEND_PID)"
echo -e "  - frontend.pid (PID: $FRONTEND_PID)"
if [ -f "electron.pid" ]; then
    ELECTRON_PID=$(cat electron.pid)
    echo -e "  - electron.pid (PID: $ELECTRON_PID)"
fi
echo ""
