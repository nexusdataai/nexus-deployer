# Nexus AI Installer - Stop Script
# This script stops all running services

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Nexus AI Installer - Stopping Services" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Function to kill process on port
function Stop-ProcessOnPort {
    param($Port, $Name)
    
    Write-Host "Stopping $Name on port $Port..." -ForegroundColor Yellow
    
    $connections = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    if ($connections) {
        $processIds = $connections | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($processId in $processIds) {
            Write-Host "  Killing process (PID: $processId)" -ForegroundColor Gray
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        }
        Write-Host "  $Name stopped" -ForegroundColor Green
    } else {
        Write-Host "  No $Name process found" -ForegroundColor Gray
    }
}

# Stop backend
Stop-ProcessOnPort -Port 8001 -Name "Backend"

# Stop frontend
Stop-ProcessOnPort -Port 5173 -Name "Frontend"

# Stop any Electron processes
Write-Host ""
Write-Host "Stopping Electron processes..." -ForegroundColor Yellow
$electronProcesses = Get-Process -Name "electron" -ErrorAction SilentlyContinue
if ($electronProcesses) {
    $electronProcesses | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host "  Electron stopped" -ForegroundColor Green
} else {
    Write-Host "  No Electron process found" -ForegroundColor Gray
}

# Also stop any Node processes that might be running Electron
$nodeProcesses = Get-Process -Name "node" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*electron*" }
if ($nodeProcesses) {
    $nodeProcesses | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host "  Electron Node processes stopped" -ForegroundColor Green
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  All services stopped" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
