# Build and Packaging Guide

## Overview

This guide explains how to build and package the Totogi Capability Installer as a desktop application using React + FastAPI + Electron.

## Prerequisites

### Development Machine Requirements

- **Node.js 18+** (for Electron and React development)
- **Python 3.11+** (for FastAPI backend)
- **Git** (for version control)

### Platform-Specific Requirements

**Windows:**
- Visual Studio Build Tools (for native modules)
- NSIS (bundled with electron-builder)

**macOS:**
- Xcode Command Line Tools
- Code signing certificate (for distribution)

**Linux:**
- Standard build tools (gcc, make)
- fpm (for DEB packages)

## Project Structure

```
nexus-deployer/
├── frontend/                    # React + Vite application
│   ├── src/
│   │   ├── components/         # React components
│   │   ├── services/           # API client services
│   │   ├── hooks/              # Custom React hooks
│   │   ├── context/            # React Context for state
│   │   ├── types/              # TypeScript types
│   │   ├── App.tsx             # Main app component
│   │   └── main.tsx            # Entry point
│   ├── public/                 # Static assets
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts
│   └── tsconfig.json
│
├── backend/                     # Python FastAPI application
│   ├── app/
│   │   ├── main.py             # FastAPI app entry point
│   │   ├── routers/            # API route handlers
│   │   │   ├── capabilities.py
│   │   │   ├── aws.py
│   │   │   ├── deployments.py
│   │   │   └── verification.py
│   │   ├── services/           # Business logic
│   │   │   ├── capability_service.py
│   │   │   ├── aws_service.py
│   │   │   ├── deployment_service.py
│   │   │   ├── verification_service.py
│   │   │   ├── log_service.py
│   │   │   └── diagnostic_service.py
│   │   ├── models/             # Pydantic models
│   │   │   ├── capability.py
│   │   │   ├── aws_config.py
│   │   │   ├── deployment.py
│   │   │   └── verification.py
│   │   └── utils/              # Utility functions
│   ├── capabilities/           # Capability definitions (JSON)
│   ├── requirements.txt
│   ├── pyproject.toml
│   └── backend.spec            # PyInstaller spec file
│
├── electron/                    # Electron wrapper
│   ├── main.js                 # Main process (spawns backend)
│   ├── preload.js              # Preload script
│   ├── package.json
│   └── assets/
│       ├── icon.ico            # Windows icon
│       ├── icon.icns           # macOS icon
│       └── icon.png            # Linux icon
│
├── scripts/
│   └── capabilities/            # Deployment scripts
│       ├── sample-capability/
│       │   ├── deploy.sh
│       │   └── verify.sh
│       └── ...
│
└── build/                       # Build scripts
    ├── build-backend.sh
    ├── build-frontend.sh
    ├── build-electron.sh
    └── build-all.sh
```

## Development Setup

### 1. Clone Repository

```bash
git clone <repository-url>
cd nexus-deployer
```

### 2. Setup Backend (Python)

```bash
cd backend

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run backend in development mode
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 3. Setup Frontend (React)

```bash
cd frontend

# Install dependencies
npm install

# Run frontend in development mode
npm run dev
# Frontend will run on http://localhost:5173
```

### 4. Setup Electron (Desktop Wrapper)

```bash
cd electron

# Install dependencies
npm install

# Run Electron in development mode
# Make sure backend and frontend are running first!
npm run dev
```

### Development Workflow

**Terminal 1 - Backend:**
```bash
cd backend
source venv/bin/activate  # or venv\Scripts\activate on Windows
uvicorn app.main:app --reload
```

**Terminal 2 - Frontend:**
```bash
cd frontend
npm run dev
```

**Terminal 3 - Electron:**
```bash
cd electron
npm run dev
```

## Building for Production

### Step 1: Build Python Backend

Create `backend/backend.spec` for PyInstaller:

```python
# backend/backend.spec
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['app/main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('capabilities', 'capabilities'),
    ],
    hiddenimports=[
        'boto3',
        'botocore',
        'uvicorn',
        'fastapi',
        'pydantic',
        'websockets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='totogi-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
```

Build backend:

```bash
cd backend

# Install PyInstaller
pip install pyinstaller

# Build executable
pyinstaller backend.spec

# Output: backend/dist/totogi-backend.exe (Windows)
#         backend/dist/totogi-backend (Mac/Linux)
```

### Step 2: Build React Frontend

```bash
cd frontend

# Install dependencies (if not already done)
npm install

# Build for production
npm run build

# Output: frontend/dist/ (static files)
```

### Step 3: Package with Electron

Update `electron/package.json`:

```json
{
  "name": "totogi-installer",
  "version": "1.0.0",
  "description": "Totogi Capability Installation Wizard",
  "main": "main.js",
  "scripts": {
    "dev": "electron .",
    "build": "electron-builder",
    "build:win": "electron-builder --win",
    "build:mac": "electron-builder --mac",
    "build:linux": "electron-builder --linux"
  },
  "build": {
    "appId": "com.totogi.installer",
    "productName": "Totogi Installer",
    "directories": {
      "output": "dist"
    },
    "files": [
      "main.js",
      "preload.js",
      "../frontend/dist/**/*"
    ],
    "extraResources": [
      {
        "from": "../backend/dist/totogi-backend${env.EXE_EXT}",
        "to": "backend/totogi-backend${env.EXE_EXT}"
      },
      {
        "from": "../scripts/capabilities",
        "to": "capabilities"
      }
    ],
    "win": {
      "target": [
        {
          "target": "nsis",
          "arch": ["x64"]
        },
        {
          "target": "portable",
          "arch": ["x64"]
        }
      ],
      "icon": "assets/icon.ico"
    },
    "nsis": {
      "oneClick": false,
      "allowToChangeInstallationDirectory": true,
      "createDesktopShortcut": true,
      "createStartMenuShortcut": true
    },
    "mac": {
      "target": "dmg",
      "icon": "assets/icon.icns",
      "category": "public.app-category.developer-tools"
    },
    "linux": {
      "target": ["AppImage", "deb"],
      "icon": "assets/icon.png",
      "category": "Development"
    }
  },
  "devDependencies": {
    "electron": "^28.0.0",
    "electron-builder": "^24.9.1"
  }
}
```

Build Electron app:

```bash
cd electron

# Install dependencies
npm install

# Build for current platform
npm run build

# Or build for specific platform:
npm run build:win    # Windows
npm run build:mac    # macOS
npm run build:linux  # Linux

# Output: electron/dist/
#   - Totogi-Installer-Setup-1.0.0.exe (Windows NSIS)
#   - Totogi-Installer-1.0.0.exe (Windows Portable)
#   - Totogi-Installer-1.0.0.dmg (macOS)
#   - Totogi-Installer-1.0.0.AppImage (Linux)
```

## Automated Build Script

Create `build/build-all.sh`:

```bash
#!/bin/bash
set -e

echo "=== Building Totogi Installer ==="

# Determine platform
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    EXE_EXT=".exe"
else
    EXE_EXT=""
fi

export EXE_EXT

# 1. Build Backend
echo "Step 1/3: Building Python backend..."
cd backend
pip install -r requirements.txt
pyinstaller backend.spec
cd ..

# 2. Build Frontend
echo "Step 2/3: Building React frontend..."
cd frontend
npm install
npm run build
cd ..

# 3. Package with Electron
echo "Step 3/3: Packaging with Electron..."
cd electron
npm install
npm run build
cd ..

echo "=== Build Complete ==="
echo "Installer location: electron/dist/"
ls -lh electron/dist/
```

Make it executable and run:

```bash
chmod +x build/build-all.sh
./build/build-all.sh
```

## Testing the Build

### Test Backend Executable

```bash
# Run the backend executable directly
cd backend/dist
./totogi-backend  # or totogi-backend.exe on Windows

# Should start FastAPI server on http://127.0.0.1:8000
# Test with: curl http://127.0.0.1:8000/api/capabilities
```

### Test Frontend Build

```bash
# Serve the built frontend
cd frontend/dist
python -m http.server 8080

# Open browser: http://localhost:8080
```

### Test Electron Package

```bash
# Install the built installer
# Windows: Run the .exe installer
# Mac: Open the .dmg and drag to Applications
# Linux: Run the .AppImage

# Or test without installing (portable mode)
cd electron/dist/win-unpacked  # or mac/linux equivalent
./Totogi-Installer.exe
```

## Troubleshooting

### Backend Build Issues

**Problem:** PyInstaller can't find boto3 modules
```bash
# Solution: Add hidden imports to backend.spec
hiddenimports=['boto3', 'botocore', 'botocore.vendored.requests']
```

**Problem:** Backend executable crashes on startup
```bash
# Solution: Run with console to see errors
# In backend.spec, set: console=True
```

### Frontend Build Issues

**Problem:** API calls fail in production
```bash
# Solution: Check that frontend is calling localhost:8000
# Update vite.config.ts if needed
```

### Electron Build Issues

**Problem:** Backend executable not found
```bash
# Solution: Check extraResources path in package.json
# Ensure backend/dist/totogi-backend exists before building
```

**Problem:** Large installer size
```bash
# Solution: Exclude unnecessary files
# Add to electron package.json:
"files": ["!**/*.map", "!**/*.ts"]
```

## Distribution

### Code Signing (Optional but Recommended)

**Windows:**
```bash
# Get code signing certificate
# Sign with signtool or configure in electron-builder
```

**macOS:**
```bash
# Get Apple Developer certificate
# Configure in electron-builder:
"mac": {
  "identity": "Developer ID Application: Your Name (TEAM_ID)"
}
```

### Auto-Update Setup

Install electron-updater:

```bash
cd electron
npm install electron-updater
```

Update `electron/main.js`:

```javascript
const { autoUpdater } = require('electron-updater');

app.whenReady().then(() => {
  autoUpdater.checkForUpdatesAndNotify();
  // ... rest of code
});
```

Configure update server in `electron/package.json`:

```json
"publish": {
  "provider": "github",
  "owner": "your-org",
  "repo": "nexus-deployer"
}
```

## CI/CD Integration

### GitHub Actions Example

Create `.github/workflows/build.yml`:

```yaml
name: Build Installer

on:
  push:
    tags:
      - 'v*'

jobs:
  build:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [windows-latest, macos-latest, ubuntu-latest]

    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Setup Node.js
        uses: actions/setup-node@v3
        with:
          node-version: '18'
      
      - name: Build Backend
        run: |
          cd backend
          pip install -r requirements.txt
          pyinstaller backend.spec
      
      - name: Build Frontend
        run: |
          cd frontend
          npm install
          npm run build
      
      - name: Build Electron
        run: |
          cd electron
          npm install
          npm run build
      
      - name: Upload Artifacts
        uses: actions/upload-artifact@v3
        with:
          name: installer-${{ matrix.os }}
          path: electron/dist/*
```

## Summary

**Development:**
1. Run backend: `uvicorn app.main:app --reload`
2. Run frontend: `npm run dev`
3. Run Electron: `npm run dev`

**Production Build:**
1. Build backend: `pyinstaller backend.spec`
2. Build frontend: `npm run build`
3. Package Electron: `npm run build`

**Output:**
- Windows: `Totogi-Installer-Setup-1.0.0.exe` (~200-250 MB)
- macOS: `Totogi-Installer-1.0.0.dmg` (~200-250 MB)
- Linux: `Totogi-Installer-1.0.0.AppImage` (~200-250 MB)
