# Totogi Installer - Simple Startup Script
# This is a simpler version that just starts both services with a delay

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Totogi Installer - Simple Startup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Stop existing processes
Write-Host "Stopping any existing processes..." -ForegroundColor Yellow

# Stop backend
$connections = Get-NetTCPConnection -LocalPort 8001 -ErrorAction SilentlyContinue
if ($connections) {
    $processIds = $connections | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($processId in $processIds) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
}

# Stop frontend
$connections = Get-NetTCPConnection -LocalPort 5173 -ErrorAction SilentlyContinue
if ($connections) {
    $processIds = $connections | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($processId in $processIds) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
}

Start-Sleep -Seconds 2
Write-Host "Done!" -ForegroundColor Green
Write-Host ""

# Check venv
if (-Not (Test-Path "backend\venv\Scripts\python.exe")) {
    Write-Host "ERROR: Virtual environment not found!" -ForegroundColor Red
    Write-Host "Please run: cd backend && python -m venv venv && venv\Scripts\pip install -r requirements.txt" -ForegroundColor Red
    pause
    exit 1
}

# Start backend
Write-Host "Starting backend server..." -ForegroundColor Yellow
$backendPath = Join-Path $PWD "backend"
$backendScript = @"
Set-Location '$backendPath'
& '.\venv\Scripts\Activate.ps1'
Write-Host 'Starting backend on http://localhost:8001...' -ForegroundColor Cyan
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
"@

Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendScript -WindowStyle Normal
Write-Host "Backend starting..." -ForegroundColor Green
Write-Host ""

# Wait for backend
Write-Host "Waiting 8 seconds for backend to start..." -ForegroundColor Yellow
Start-Sleep -Seconds 8
Write-Host "Backend should be ready!" -ForegroundColor Green
Write-Host ""

# Start frontend
Write-Host "Starting frontend server..." -ForegroundColor Yellow
$frontendPath = Join-Path $PWD "frontend"
$frontendScript = @"
Set-Location '$frontendPath'
Write-Host 'Starting frontend on http://localhost:5173...' -ForegroundColor Cyan
npm run dev
"@

Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendScript -WindowStyle Normal
Write-Host "Frontend starting..." -ForegroundColor Green
Write-Host ""

# Wait for frontend
Write-Host "Waiting 8 seconds for frontend to start..." -ForegroundColor Yellow
Start-Sleep -Seconds 8
Write-Host ""

# Start Electron desktop app
Write-Host "Starting Electron desktop app..." -ForegroundColor Yellow
$electronPath = Join-Path $PWD "electron"

if (Test-Path "$electronPath\node_modules") {
    $electronScript = @"
Set-Location '$electronPath'
Write-Host 'Starting Electron desktop app...' -ForegroundColor Cyan
Write-Host 'Electron will wait for frontend server to be ready...' -ForegroundColor Gray
npm run dev
"@
    
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $electronScript -WindowStyle Normal
    Write-Host "Electron desktop app starting..." -ForegroundColor Green
    Write-Host "(Electron will wait for frontend to be ready)" -ForegroundColor Gray
    Write-Host ""
    Start-Sleep -Seconds 3
} else {
    Write-Host "Electron dependencies not found. Skipping desktop app." -ForegroundColor Yellow
    Write-Host "To install: cd electron && npm install" -ForegroundColor Gray
    Write-Host ""
}

# Open browser
Write-Host "Opening browser..." -ForegroundColor Yellow
Start-Sleep -Seconds 2
Start-Process "http://localhost:5173"

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Startup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Backend:  http://localhost:8001" -ForegroundColor Cyan
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
Write-Host "Press any key to close this window..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
