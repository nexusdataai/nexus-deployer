# build-windows.ps1 - Complete Windows build script for Nexus AI Capability Installer
# Creates a distributable Windows installer (.exe)
#
# Usage:
#   .\build-windows.ps1           # Normal build (cleans build artifacts)
#   .\build-windows.ps1 -Clean    # Deep clean (also removes node_modules, venv)

param(
    [switch]$Clean = $false
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Nexus AI Capability Installer - Windows Build" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Build started at: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
if ($Clean) {
    Write-Host "Mode: DEEP CLEAN BUILD" -ForegroundColor Magenta
}

# Set environment variable for electron-builder
$env:EXE_EXT = ".exe"

# Navigate to project root
Set-Location $ScriptDir

# ============================================
# Deep Clean (if -Clean flag is set)
# ============================================
if ($Clean) {
    Write-Host "`n[0/3] Deep cleaning all build artifacts..." -ForegroundColor Magenta
    
    # Clean backend
    Write-Host "  Cleaning backend..."
    if (Test-Path "backend\venv") {
        Remove-Item -Recurse -Force "backend\venv" -ErrorAction SilentlyContinue
    }
    if (Test-Path "backend\dist") {
        Remove-Item -Recurse -Force "backend\dist" -ErrorAction SilentlyContinue
    }
    if (Test-Path "backend\build") {
        Remove-Item -Recurse -Force "backend\build" -ErrorAction SilentlyContinue
    }
    
    # Clean frontend
    Write-Host "  Cleaning frontend..."
    if (Test-Path "frontend\node_modules") {
        Remove-Item -Recurse -Force "frontend\node_modules" -ErrorAction SilentlyContinue
    }
    if (Test-Path "frontend\dist") {
        Remove-Item -Recurse -Force "frontend\dist" -ErrorAction SilentlyContinue
    }
    
    # Clean electron
    Write-Host "  Cleaning electron..."
    if (Test-Path "electron\node_modules") {
        Remove-Item -Recurse -Force "electron\node_modules" -ErrorAction SilentlyContinue
    }
    if (Test-Path "electron\dist") {
        Remove-Item -Recurse -Force "electron\dist" -ErrorAction SilentlyContinue
    }
    if (Test-Path "electron\frontend") {
        Remove-Item -Recurse -Force "electron\frontend" -ErrorAction SilentlyContinue
    }
    
    # Clean PyInstaller cache
    $pyinstallerCache = "$env:LOCALAPPDATA\pyinstaller"
    if (Test-Path $pyinstallerCache) {
        Write-Host "  Cleaning PyInstaller cache..."
        Remove-Item -Recurse -Force $pyinstallerCache -ErrorAction SilentlyContinue
    }
    
    Write-Host "  Deep clean complete!" -ForegroundColor Green
}

# ============================================
# Step 1: Build Python Backend with PyInstaller
# ============================================
Write-Host "`n[1/3] Building Python Backend..." -ForegroundColor Yellow
Set-Location "$ScriptDir\backend"

# Create virtual environment if it doesn't exist
if (-not (Test-Path "venv")) {
    Write-Host "  Creating virtual environment..."
    python -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to create virtual environment"
        exit 1
    }
}

# Activate virtual environment
Write-Host "  Activating virtual environment..."
& ".\venv\Scripts\Activate.ps1"

# Install dependencies
Write-Host "  Installing Python dependencies..."
pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to install Python dependencies"
    exit 1
}

# Install PyInstaller
Write-Host "  Installing PyInstaller..."
pip install pyinstaller --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to install PyInstaller"
    exit 1
}

# Clean previous build artifacts thoroughly
Write-Host "  Cleaning previous backend build artifacts..."
if (Test-Path "dist") {
    Remove-Item -Recurse -Force "dist"
}
if (Test-Path "build") {
    Remove-Item -Recurse -Force "build"
}
# Clean PyInstaller cache
$pyinstallerCache = "$env:LOCALAPPDATA\pyinstaller"
if (Test-Path $pyinstallerCache) {
    Write-Host "  Cleaning PyInstaller cache..."
    Remove-Item -Recurse -Force $pyinstallerCache -ErrorAction SilentlyContinue
}
# Clean __pycache__ directories
Write-Host "  Cleaning __pycache__ directories..."
Get-ChildItem -Path "." -Directory -Recurse -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
# Clean .pyc files
Get-ChildItem -Path "." -File -Recurse -Filter "*.pyc" | Remove-Item -Force -ErrorAction SilentlyContinue

# Run PyInstaller with clean build
Write-Host "  Running PyInstaller (clean build)..."
pyinstaller backend.spec --clean --noconfirm
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller build failed"
    exit 1
}

# Generate template manifest
Write-Host "  Generating template manifest..."
python scripts/generate_template_manifest.py "$ScriptDir\deploy\templates" "$ScriptDir\deploy\templates\template-manifest.json"
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Template manifest generation failed - continuing build"
} else {
    Write-Host "  Template manifest generated successfully" -ForegroundColor Green
}

# Verify output
if (-not (Test-Path "dist\nexus-installer-backend.exe")) {
    Write-Error "Backend build failed - nexus-installer-backend.exe not found"
    exit 1
}

$backendSize = (Get-Item "dist\nexus-installer-backend.exe").Length / 1MB
Write-Host "  Backend build complete! Size: $([math]::Round($backendSize, 2)) MB" -ForegroundColor Green

# ============================================
# Step 2: Build React Frontend with Vite
# ============================================
Write-Host "`n[2/3] Building React Frontend..." -ForegroundColor Yellow
Set-Location "$ScriptDir\frontend"

# Install npm dependencies if needed
if (-not (Test-Path "node_modules")) {
    Write-Host "  Installing npm dependencies..."
    npm install
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to install npm dependencies"
        exit 1
    }
}

# Clean previous build thoroughly
Write-Host "  Cleaning previous frontend build..."
if (Test-Path "dist") {
    Remove-Item -Recurse -Force "dist"
}
# Clean Vite cache
if (Test-Path "node_modules\.vite") {
    Remove-Item -Recurse -Force "node_modules\.vite" -ErrorAction SilentlyContinue
}

# Build frontend
Write-Host "  Building with Vite..."
npm run build
if ($LASTEXITCODE -ne 0) {
    Write-Error "Frontend build failed"
    exit 1
}

# Verify output
if (-not (Test-Path "dist\index.html")) {
    Write-Error "Frontend build failed - dist/index.html not found"
    exit 1
}

Write-Host "  Frontend build complete!" -ForegroundColor Green

# ============================================
# Step 3: Package with Electron Builder
# ============================================
Write-Host "`n[3/3] Packaging with Electron Builder..." -ForegroundColor Yellow
Set-Location "$ScriptDir\electron"

# Install npm dependencies if needed
if (-not (Test-Path "node_modules")) {
    Write-Host "  Installing npm dependencies..."
    npm install
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to install Electron dependencies"
        exit 1
    }
}

# Clean previous Electron build thoroughly
Write-Host "  Cleaning previous Electron build..."
if (Test-Path "dist") {
    Remove-Item -Recurse -Force "dist"
}
# Clean electron-builder cache
$electronBuilderCache = "$env:LOCALAPPDATA\electron-builder\Cache"
if (Test-Path $electronBuilderCache) {
    Write-Host "  Note: Electron builder cache exists at $electronBuilderCache"
    Write-Host "  (Not cleaning to speed up builds - delete manually if needed)"
}

# Copy frontend dist to electron folder for packaging
Write-Host "  Copying frontend build to electron folder..."
if (Test-Path "frontend") {
    Remove-Item -Recurse -Force "frontend" -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Path "frontend\dist" -Force | Out-Null
Copy-Item -Path "$ScriptDir\frontend\dist\*" -Destination "frontend\dist" -Recurse -Force

# Build Windows installer
Write-Host "  Running electron-builder for Windows..."
npm run build:win
if ($LASTEXITCODE -ne 0) {
    Write-Error "Electron builder failed"
    exit 1
}

Write-Host "  Electron packaging complete!" -ForegroundColor Green

# ============================================
# Build Summary
# ============================================
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "BUILD COMPLETE!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Build finished at: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

Write-Host "`nOutput files in electron/dist/:" -ForegroundColor White
Get-ChildItem -Path "dist" -Filter "*.exe" | ForEach-Object {
    $size = $_.Length / 1MB
    Write-Host "  - $($_.Name) ($([math]::Round($size, 2)) MB)" -ForegroundColor Yellow
}

Write-Host "`nTo distribute:" -ForegroundColor White
Write-Host "  1. Copy the installer .exe to your distribution location"
Write-Host "  2. Customers can run the installer to install the application"
Write-Host "  3. Or use the portable .exe for no-install usage"

# Return to project root
Set-Location $ScriptDir
