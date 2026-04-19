# Startup Guide

## Quick Start

### Windows

**Option 1: Double-click the batch file**
```
start-app.bat
```

**Option 2: Run PowerShell script**
```powershell
.\start-app.ps1
```

### Linux / Mac

**Run the bash script:**
```bash
./start-app.sh
```

**Note:** First time, you may need to make it executable:
```bash
chmod +x start-app.sh stop-app.sh
./start-app.sh
```

### What the startup script does:

1. ✅ Kills any existing processes (port 8001, 5173, Electron)
2. ✅ Creates Python virtual environment (if needed)
3. ✅ Installs Python dependencies (if needed)
4. ✅ Installs frontend npm dependencies (if needed)
5. ✅ Installs Electron dependencies (if needed)
6. ✅ Starts Python backend on port 8001
7. ✅ Starts Vite frontend on port 5173
8. ✅ Launches Electron desktop application

## Stopping the Application

**Option 1: Close the Electron window**
- The startup script will automatically clean up backend and frontend

**Option 2: Use the stop script**

**Windows:**
```
stop-app.bat
```
or
```powershell
.\stop-app.ps1
```

**Linux/Mac:**
```bash
./stop-app.sh
```

## Manual Startup (Alternative)

If you prefer to run each component separately:

### Terminal 1 - Backend
```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app/main.py
```

### Terminal 2 - Frontend
```bash
cd frontend
npm install
npm run dev
```

### Terminal 3 - Electron
```bash
cd electron
npm install
npm run dev
```

## Troubleshooting

### Windows: "Execution of scripts is disabled on this system"

Run this in PowerShell as Administrator:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Linux/Mac: "Permission denied"

Make the scripts executable:
```bash
chmod +x start-app.sh stop-app.sh
```

### Port already in use

The startup script automatically kills processes on ports 8001 and 5173. If you still have issues:

**Windows:**
```powershell
.\stop-app.ps1
```

**Linux/Mac:**
```bash
./stop-app.sh
```

### Python not found

Make sure Python 3.11+ is installed and in your PATH:
```bash
python --version
```

### Node.js not found

Make sure Node.js 18+ is installed:
```bash
node --version
```

## First Time Setup

The first run will take longer because it needs to:
- Create Python virtual environment
- Install Python dependencies (~2-3 minutes)
- Install npm dependencies (~2-3 minutes)

Subsequent runs will be much faster!

## Ports Used

- **8001**: Python FastAPI backend
- **5173**: Vite frontend dev server
- **Electron**: Desktop application (connects to above)

## Development Tips

- Backend auto-reloads on Python file changes
- Frontend hot-reloads on React file changes
- Electron needs restart to see changes in main.js
- Check Electron DevTools (F12) for frontend errors
- Check terminal for backend errors
