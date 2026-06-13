/**
 * Nexus AI Capability Installer - Electron Main Process
 * 
 * Uses StartupOrchestrator for coordinated startup sequence:
 * 1. Spawn backend process
 * 2. Wait for backend to be ready (health check)
 * 3. Load frontend only after backend is ready
 * 
 * Feature: startup-health-check
 * Requirements: 2.1, 2.6, 9.1, 9.2, 9.3
 */

const { app, BrowserWindow, ipcMain } = require('electron');
const { execSync } = require('child_process');
const path = require('path');
const { StartupOrchestrator, StartupPhase } = require('./startup/orchestrator');

const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged;

let mainWindow = null;
let isQuitting = false;
let startupOrchestrator = null;
let lastSentStatus = { phase: '', progress: -1 };  // Track last sent status to avoid flooding

/**
 * Get the backend executable path
 */
function getBackendPath() {
  const backendName = process.platform === 'win32' 
    ? 'nexus-installer-backend.exe' 
    : 'nexus-installer-backend';
  
  return path.join(
    process.resourcesPath,
    'backend',
    backendName
  );
}

/**
 * Kill any orphaned backend processes by name
 * This handles cases where the process reference was lost
 */
function killOrphanedBackendProcesses() {
  console.log('[Electron] Checking for orphaned backend processes...');
  
  try {
    if (process.platform === 'win32') {
      execSync('taskkill /F /IM nexus-installer-backend.exe /T', { stdio: 'ignore' });
      console.log('[Electron] Killed orphaned nexus-installer-backend.exe processes');
    } else {
      execSync('pkill -f nexus-installer-backend', { stdio: 'ignore' });
    }
  } catch (error) {
    // No processes found or already dead - this is fine
    console.log('[Electron] No orphaned backend processes found');
  }
}

/**
 * Wait for frontend dev server (development mode only)
 */
async function waitForFrontendServer(url, maxAttempts = 30) {
  const http = require('http');
  
  for (let i = 0; i < maxAttempts; i++) {
    try {
      await new Promise((resolve, reject) => {
        const req = http.get(url, (res) => {
          resolve(res);
        });
        req.on('error', reject);
        req.setTimeout(1000, () => {
          req.destroy();
          reject(new Error('Timeout'));
        });
      });
      console.log(`[Electron] Frontend server at ${url} is ready!`);
      return true;
    } catch (error) {
      console.log(`[Electron] Attempt ${i + 1}/${maxAttempts}: Waiting for frontend...`);
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
  }
  console.error(`[Electron] Frontend server not available after ${maxAttempts} seconds`);
  return false;
}

/**
 * Send startup status to renderer process
 * Throttled to only send when status meaningfully changes
 */
function sendStartupStatus(status) {
  if (mainWindow && mainWindow.webContents) {
    const currentPhase = status.phase || '';
    const currentProgress = Math.floor((status.progress || 0) / 10) * 10;
    
    // Always send if phase changed, or if progress changed by at least 10%
    // Also always send 'ready' and 'error' phases
    const isImportantPhase = currentPhase === 'ready' || currentPhase === 'error';
    const phaseChanged = currentPhase !== lastSentStatus.phase;
    const progressChanged = currentProgress !== lastSentStatus.progress;
    
    if (isImportantPhase || phaseChanged || progressChanged) {
      lastSentStatus = { phase: currentPhase, progress: currentProgress };
      mainWindow.webContents.send('startup-status', status);
    }
  }
}

/**
 * Create the main browser window
 */
async function createWindow() {
  console.log('[Electron] Creating main window...');
  
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    },
    title: 'Nexus AI Capability Installer',
    show: true, // Show immediately so user sees the app is starting
    backgroundColor: '#1a1a2e', // Dark background while loading
  });

  if (isDev) {
    // Development mode: Wait for Vite dev server
    console.log('[Electron] Waiting for frontend server at http://localhost:5173...');
    const serverReady = await waitForFrontendServer('http://localhost:5173');
    
    if (serverReady) {
      console.log('[Electron] Loading application from Vite dev server...');
      await mainWindow.loadURL('http://localhost:5173');
      mainWindow.webContents.openDevTools();
    } else {
      console.error('[Electron] Frontend server not available');
      mainWindow.loadURL('data:text/html,<h1>Error: Frontend server not available</h1><p>Please make sure the frontend is running on http://localhost:5173</p><p>Run: cd frontend && npm run dev</p>');
    }
  } else {
    // Production: Load from built files
    const indexPath = path.join(__dirname, 'frontend', 'dist', 'index.html');
    console.log('[Electron] Loading from:', indexPath);
    try {
      await mainWindow.loadFile(indexPath);
      // Open DevTools in production for debugging (remove this later)
      // mainWindow.webContents.openDevTools();
    } catch (err) {
      console.error('[Electron] Failed to load index.html:', err);
      mainWindow.loadURL(`data:text/html,<h1>Error loading application</h1><p>${err.message}</p><p>Path: ${indexPath}</p>`);
    }
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  // Handle window close
  mainWindow.on('close', () => {
    if (!isQuitting) {
      // Window is closing but app may continue (on macOS)
    }
  });
}

/**
 * Initialize the application with startup orchestrator
 */
async function initializeApp() {
  console.log('[Electron] Initializing application...');
  console.log('[Electron] Development mode:', isDev);
  console.log('[Electron] Resources path:', process.resourcesPath);
  console.log('[Electron] App packaged:', app.isPackaged);
  console.log('[Electron] App path:', app.getAppPath());
  console.log('[Electron] User data path:', app.getPath('userData'));
  
  // CRITICAL: Create window FIRST so user sees something immediately
  // This prevents the "app not opening" issue where health checks block window creation
  console.log('[Electron] Creating window immediately...');
  await createWindow();
  
  // Send initial loading status
  sendStartupStatus({
    phase: StartupPhase.IDLE,
    progress: 0,
    message: 'Starting application...',
  });
  
  // Log backend path for debugging
  const backendPath = isDev ? null : getBackendPath();
  console.log('[Electron] Backend path:', backendPath);
  
  // Create startup orchestrator
  startupOrchestrator = new StartupOrchestrator({
    backendPath: backendPath,
    resourcesPath: isDev ? null : process.resourcesPath,
    isDev: isDev,
    backendStartupTimeoutMs: 30000,
    maxRestartAttempts: 3,
    healthPollConfig: {
      maxAttempts: 300,  // 30 seconds at 100ms initial
      initialDelayMs: 100,
      maxDelayMs: 2000,
    },
    onStatusChange: (status) => {
      console.log(`[Electron] Startup status: ${status.phase} (${status.progress}%)`);
      sendStartupStatus(status);
    },
    onLog: (message, level) => {
      if (level === 'error') {
        console.error(`[Startup] ${message}`);
      } else {
        console.log(`[Startup] ${message}`);
      }
    },
  });

  // Start the orchestrated startup sequence (window already visible)
  const result = await startupOrchestrator.start();
  
  if (result.success) {
    console.log(`[Electron] Backend ready in ${result.startupTimeMs}ms`);
    // Note: Ready status already sent by orchestrator via onStatusChange callback
  } else {
    console.error(`[Electron] Startup failed: ${result.error}`);
    
    // Send error status with more details
    sendStartupStatus({
      phase: StartupPhase.ERROR,
      progress: 0,
      message: result.error || 'Backend failed to start',
      error: result.error,
    });
  }
}

// ============================================
// IPC Handlers
// ============================================

// Handle startup status request from renderer
ipcMain.handle('get-startup-status', () => {
  if (startupOrchestrator) {
    return startupOrchestrator.getStatus();
  }
  return { phase: 'unknown', progress: 0, message: 'Not initialized' };
});

// Handle retry request from renderer
ipcMain.handle('retry-startup', async () => {
  console.log('[Electron] Retry startup requested');
  if (startupOrchestrator) {
    const result = await startupOrchestrator.handleBackendCrash();
    return { success: result };
  }
  return { success: false, error: 'Orchestrator not initialized' };
});

// ============================================
// App Lifecycle Events
// ============================================

app.whenReady().then(() => {
  initializeApp();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  console.log('[Electron] Application is quitting...');
  isQuitting = true;
});

app.on('quit', async () => {
  console.log('[Electron] Shutting down...');
  
  // Stop the orchestrator (kills backend)
  if (startupOrchestrator) {
    await startupOrchestrator.stop();
  }
  
  // Also kill any orphaned processes (safety net)
  killOrphanedBackendProcesses();
  
  console.log('[Electron] Cleanup complete');
});

app.on('will-quit', (event) => {
  console.log('[Electron] Will quit - ensuring backend is terminated...');
  
  if (startupOrchestrator && startupOrchestrator.backendProcess) {
    event.preventDefault();
    
    startupOrchestrator.stop().then(() => {
      killOrphanedBackendProcesses();
      setTimeout(() => {
        app.quit();
      }, 500);
    });
  }
});
