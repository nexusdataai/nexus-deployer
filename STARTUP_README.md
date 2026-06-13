# Nexus AI Installer - Startup Guide

## Quick Start

### Windows

**Option 1: Simple Startup (Recommended)**
```powershell
.\start-app-simple.ps1
```
Or double-click `start-app-simple.bat`

**Option 2: Smart Startup (with health checks)**
```powershell
.\start-app.ps1
```
Or double-click `start-app.bat`

### Linux / macOS

```bash
./start-app.sh
```

## Which Startup Script to Use?

### Simple Startup (`start-app-simple.ps1`)
- ✅ **Recommended for most users**
- Starts backend, waits 8 seconds, then starts frontend
- No health checking - just fixed delays
- More reliable on some systems
- Faster startup

### Smart Startup (`start-app.ps1`)
- Includes backend health checking
- Waits for backend to confirm ready before starting frontend
- May have issues with some PowerShell configurations
- Use if you want guaranteed backend readiness

## What the Startup Script Does

The smart startup script automatically handles:

1. ✅ **Checks for existing processes** - Detects if backend (port 8001) or frontend (port 5173) are already running
2. ✅ **Stops existing processes** - Cleanly stops any running instances to avoid conflicts
3. ✅ **Starts backend with venv** - Activates Python virtual environment and starts FastAPI server
4. ✅ **Health check** - Waits for backend to be ready (up to 30 seconds)
5. ✅ **Starts frontend** - Launches Vite dev server only after backend is confirmed ready
6. ✅ **Opens browser** - Automatically opens http://localhost:5173

## Prerequisites

### First Time Setup

Before running the startup script for the first time, you need to set up the environment:

#### 1. Python Backend Setup

```bash
cd backend
python -m venv venv

# Windows
venv\Scripts\activate
pip install -r requirements.txt

# Linux/macOS
source venv/bin/activate
pip install -r requirements.txt
```

#### 2. Frontend Setup

```bash
cd frontend
npm install
```

## Stopping the Application

### Windows

```powershell
.\stop-app.ps1
```

Or simply close the backend and frontend windows.

### Linux / macOS

```bash
./stop-app.sh
```

## Troubleshooting

### Backend Won't Start

**Error: "Virtual environment not found"**
```bash
cd backend
python -m venv venv
venv\Scripts\pip install -r requirements.txt  # Windows
# or
source venv/bin/activate && pip install -r requirements.txt  # Linux/macOS
```

**Error: "Backend failed to start after 30 seconds"**
- Check `backend.log` (Linux/macOS) or the backend window (Windows) for errors
- Common issues:
  - Port 8001 already in use by another application
  - Missing Python dependencies
  - Python version incompatibility (requires Python 3.11+)

### Frontend Won't Start

**Error: "npm: command not found"**
- Install Node.js from https://nodejs.org/

**Error: "Cannot find module"**
```bash
cd frontend
npm install
```

**Error: "Port 5173 already in use"**
- Another Vite server is running
- Run `stop-app.ps1` or `stop-app.sh` to clean up

### Connection Issues

**Error: "Failed to load capabilities"**
- The frontend started before the backend was ready
- Solution: The new startup script prevents this by waiting for backend health check
- If you still see this, refresh the browser page

**Error: "Backend not reachable"**
- Check if backend is running: http://localhost:8001/api/health
- Should return: `{"status":"healthy","service":"nexus-installer-backend","version":"1.0.0"}`

## Manual Startup (Alternative)

If you prefer to start services manually:

### Terminal 1 - Backend
```bash
cd backend
# Windows
venv\Scripts\activate
# Linux/macOS
source venv/bin/activate

python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

### Terminal 2 - Frontend
```bash
cd frontend
npm run dev
```

### Browser
Open http://localhost:5173

## Ports Used

- **8001** - Backend API (FastAPI)
- **5173** - Frontend (Vite dev server)

## Logs

### Windows
- Backend logs appear in the backend window
- Frontend logs appear in the frontend window

### Linux/macOS
- `backend.log` - Backend server logs
- `frontend.log` - Frontend server logs
- Process IDs saved in `backend.pid` and `frontend.pid`

## Development Mode

The startup scripts run in development mode with:
- **Backend**: Auto-reload on code changes (`--reload` flag)
- **Frontend**: Hot Module Replacement (HMR) enabled
- **Source maps**: Enabled for debugging

## Production Build

For production deployment, see `BUILD_GUIDE.md` for instructions on:
- Building the frontend with Vite
- Packaging the backend with PyInstaller
- Creating Electron desktop application

## Architecture

```
┌─────────────────────────────────────┐
│  Browser (http://localhost:5173)   │
└─────────────────┬───────────────────┘
                  │
                  │ HTTP/WebSocket
                  ▼
┌─────────────────────────────────────┐
│  Vite Dev Server (Port 5173)       │
│  - React Frontend                   │
│  - Hot Module Replacement           │
└─────────────────┬───────────────────┘
                  │
                  │ API Calls
                  ▼
┌─────────────────────────────────────┐
│  FastAPI Backend (Port 8001)       │
│  - Python + uvicorn                 │
│  - boto3 (AWS SDK)                  │
│  - Auto-reload enabled              │
└─────────────────┬───────────────────┘
                  │
                  │ boto3
                  ▼
┌─────────────────────────────────────┐
│  AWS Services                       │
│  - IAM/STS (Role assumption)        │
│  - CloudFormation                   │
└─────────────────────────────────────┘
```

## Next Steps

Once the application is running:
1. Click "Begin Deployment"
2. Select a capability
3. Choose environment
4. Configure AWS credentials
5. Deploy!

For more information, see:
- `QUICK_START_GUIDE.md` - Detailed usage guide
- `BUILD_GUIDE.md` - Build and packaging instructions
- `MVP_PROGRESS.md` - Current implementation status
