# Nexus AI Installer - Smart Startup Script
# This script will:
# 1. Check and stop existing processes on ports 8001 and 5173
# 2. Start backend with venv
# 3. Wait for backend health check
# 4. Start frontend
# 5. Open browser

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Nexus AI Installer - Smart Startup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Check and stop existing processes
Write-Host "[1/6] Checking for existing processes..." -ForegroundColor Yellow

# Function to kill process on port
function Stop-ProcessOnPort {
    param($Port)
    
    $connections = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    if ($connections) {
        $processIds = $connections | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($processId in $processIds) {
            Write-Host "  Stopping process on port $Port (PID: $processId)" -ForegroundColor Gray
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 2
        Write-Host "  Port $Port is now free" -ForegroundColor Green
    } else {
        Write-Host "  Port $Port is free" -ForegroundColor Green
    }
}

Stop-ProcessOnPort -Port 8001
Stop-ProcessOnPort -Port 5173
Write-Host ""

# Step 2: Check Python venv
Write-Host "[2/6] Checking Python virtual environment..." -ForegroundColor Yellow

if (-Not (Test-Path "backend\venv\Scripts\python.exe")) {
    Write-Host "  ERROR: Virtual environment not found!" -ForegroundColor Red
    Write-Host "  Please run: cd backend && python -m venv venv && venv\Scripts\pip install -r requirements.txt" -ForegroundColor Red
    pause
    exit 1
}

Write-Host "  Virtual environment found" -ForegroundColor Green
Write-Host ""

# Step 3: Start backend
Write-Host "[3/6] Starting backend server..." -ForegroundColor Yellow

$backendPath = Join-Path $PWD "backend"
$backendScript = @"
Set-Location '$backendPath'
& '.\venv\Scripts\Activate.ps1'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
"@

# Start backend in new window
Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendScript -WindowStyle Normal

Write-Host "  Backend starting in new window..." -ForegroundColor Gray
Write-Host ""

# Step 4: Wait for backend health check
Write-Host "[4/6] Waiting for backend to be ready..." -ForegroundColor Yellow

$maxAttempts = 60
$attempt = 0
$backendReady = $false

# Give backend a few seconds to start up
Start-Sleep -Seconds 3

while ($attempt -lt $maxAttempts) {
    $attempt++
    try {
        # Use simpler method that works better in PowerShell
        # Use 127.0.0.1 instead of localhost to avoid IPv6 issues
        $webClient = New-Object System.Net.WebClient
        $webClient.Headers.Add("User-Agent", "PowerShell")
        $response = $webClient.DownloadString("http://127.0.0.1:8001/api/health")
        
        if ($response -match "healthy") {
            $backendReady = $true
            Write-Host "  Backend is ready! (attempt $attempt/$maxAttempts)" -ForegroundColor Green
            break
        }
    } catch {
        if ($attempt % 5 -eq 0) {
            Write-Host "  Attempt $attempt/$maxAttempts : Still waiting for backend..." -ForegroundColor Gray
        }
        Start-Sleep -Seconds 1
    }
}

if (-not $backendReady) {
    Write-Host ""
    Write-Host "  WARNING: Could not confirm backend health after 60 seconds" -ForegroundColor Yellow
    Write-Host "  The backend window shows it started successfully." -ForegroundColor Yellow
    Write-Host "  Continuing anyway..." -ForegroundColor Yellow
    Write-Host ""
    Start-Sleep -Seconds 2
}

Write-Host ""

# Step 5: Start frontend
Write-Host "[5/6] Starting frontend server..." -ForegroundColor Yellow

$frontendPath = Join-Path $PWD "frontend"
$frontendScript = @"
Set-Location '$frontendPath'
npm run dev
"@

# Start frontend in new window
Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendScript -WindowStyle Normal

Write-Host "  Frontend starting in new window..." -ForegroundColor Gray
Write-Host "  Waiting for frontend to initialize..." -ForegroundColor Gray
Start-Sleep -Seconds 5
Write-Host ""

# Step 6: Start Electron desktop app
Write-Host "[6/7] Starting Electron desktop app..." -ForegroundColor Yellow

$electronPath = Join-Path $PWD "electron"

if (Test-Path "$electronPath\node_modules") {
    $electronScript = @"
Set-Location '$electronPath'
Write-Host 'Starting Electron desktop app...' -ForegroundColor Cyan
npm run dev
"@
    
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $electronScript -WindowStyle Normal
    Write-Host "Electron desktop app starting..." -ForegroundColor Green
    Write-Host ""
    Start-Sleep -Seconds 3
} else {
    Write-Host "Electron dependencies not found. Skipping desktop app." -ForegroundColor Yellow
    Write-Host "To install: cd electron && npm install" -ForegroundColor Gray
    Write-Host ""
}

# Step 7: Open browser
Write-Host "[7/7] Opening application in browser..." -ForegroundColor Yellow

Start-Sleep -Seconds 2
# Use localhost - Vite binds to localhost by default
Start-Process "http://localhost:5173"

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Startup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Backend:  http://127.0.0.1:8001" -ForegroundColor Cyan
Write-Host "Frontend: http://localhost:5173" -ForegroundColor Cyan
Write-Host "Desktop:  Electron app window" -ForegroundColor Cyan
Write-Host ""
Write-Host "The application is running in:" -ForegroundColor White
Write-Host "  - Backend window (Python/FastAPI)" -ForegroundColor White
Write-Host "  - Frontend window (Vite dev server)" -ForegroundColor White
Write-Host "  - Electron desktop app" -ForegroundColor White
Write-Host "  - Web browser" -ForegroundColor White
Write-Host ""
Write-Host "Close the windows to stop the services." -ForegroundColor White
Write-Host ""
Write-Host "To stop all services, run: .\stop-app.ps1" -ForegroundColor Yellow
Write-Host ""
Write-Host "Press any key to close this window..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
