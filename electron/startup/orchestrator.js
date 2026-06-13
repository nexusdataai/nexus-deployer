/**
 * Startup Orchestrator for Electron Application
 * 
 * Coordinates the startup sequence: spawn backend, wait for ready, load frontend.
 * Handles crash detection and recovery.
 * 
 * Feature: startup-health-check
 * Requirements: 2.1, 2.4, 2.6, 9.1, 9.2
 */

const { spawn, execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const { HealthPoller } = require('./health-poller');

/**
 * Startup phases
 */
const StartupPhase = {
  IDLE: 'idle',
  SPAWNING_BACKEND: 'spawning_backend',
  WAITING_FOR_BACKEND: 'waiting_for_backend',
  LOADING_FRONTEND: 'loading_frontend',
  READY: 'ready',
  ERROR: 'error',
  RECOVERING: 'recovering',
};

/**
 * Default configuration for startup orchestrator
 */
const DEFAULT_CONFIG = {
  backendStartupTimeoutMs: 30000,  // 30 seconds
  maxRestartAttempts: 3,
  crashDetectionIntervalMs: 1000,  // Check every second
  healthPollConfig: {
    maxAttempts: 300,
    initialDelayMs: 100,
    maxDelayMs: 2000,
  },
};

/**
 * Startup Orchestrator class
 */
class StartupOrchestrator {
  /**
   * Create a new StartupOrchestrator
   * @param {Object} options - Configuration options
   * @param {string} options.backendPath - Path to backend executable
   * @param {string} options.resourcesPath - Path to resources directory
   * @param {boolean} options.isDev - Whether running in development mode
   * @param {Object} options.healthPollConfig - Health poller configuration
   * @param {number} options.backendStartupTimeoutMs - Backend startup timeout
   * @param {number} options.maxRestartAttempts - Max restart attempts on crash
   * @param {Function} options.onStatusChange - Callback for status changes
   * @param {Function} options.onLog - Callback for log messages
   */
  constructor(options = {}) {
    this.config = { ...DEFAULT_CONFIG, ...options };
    this.backendPath = options.backendPath;
    this.resourcesPath = options.resourcesPath;
    this.isDev = options.isDev || false;
    
    this.onStatusChange = options.onStatusChange || (() => {});
    this.onLog = options.onLog || console.log;
    
    this.healthPoller = new HealthPoller({
      ...this.config.healthPollConfig,
      onAttempt: (info) => this._handleHealthAttempt(info),
    });
    
    this.backendProcess = null;
    this.phase = StartupPhase.IDLE;
    this.restartCount = 0;
    this.crashDetectionInterval = null;
    this.lastHealthResponse = null;
    this.startTime = null;
    this.lastSentProgress = -1;  // Track last sent progress to avoid duplicate updates
  }

  /**
   * Start the full application
   * @returns {Promise<{success: boolean, error?: string, phase: string}>}
   */
  async start() {
    this.startTime = Date.now();
    this._log('Starting application...');
    
    try {
      // Step 1: Start backend
      await this.startBackend();
      
      // Step 2: Wait for backend to be ready
      const ready = await this.waitForBackend();
      
      if (!ready) {
        this._setPhase(StartupPhase.ERROR);
        return {
          success: false,
          error: 'Backend failed to become ready within timeout',
          phase: this.phase,
        };
      }
      
      // Step 3: Start crash detection
      this._startCrashDetection();
      
      // Step 4: Mark as ready (frontend is already loaded, just waiting for backend)
      // Note: READY phase was already set in waitForBackend() when health check succeeded
      // Don't override it with LOADING_FRONTEND
      
      return {
        success: true,
        phase: this.phase,
        startupTimeMs: Date.now() - this.startTime,
      };
      
    } catch (error) {
      this._log(`Startup failed: ${error.message}`, 'error');
      this._setPhase(StartupPhase.ERROR);
      return {
        success: false,
        error: error.message,
        phase: this.phase,
      };
    }
  }

  /**
   * Start the backend process
   * @returns {Promise<void>}
   */
  async startBackend() {
    this._setPhase(StartupPhase.SPAWNING_BACKEND);
    
    if (this.isDev) {
      this._log('Development mode - expecting backend already running');
      return;
    }
    
    if (!this.backendPath) {
      throw new Error('Backend path not configured');
    }
    
    // Check if backend executable exists
    if (!fs.existsSync(this.backendPath)) {
      this._log(`Backend executable not found at: ${this.backendPath}`, 'error');
      throw new Error(`Backend executable not found: ${this.backendPath}`);
    }
    
    this._log(`Starting backend: ${this.backendPath}`);
    this._log(`Resources path: ${this.resourcesPath}`);
    
    // Create log file for backend output
    const { app } = require('electron');
    const logDir = app.getPath('userData');
    const logPath = path.join(logDir, 'backend.log');
    this._log(`Backend log file: ${logPath}`);
    
    // Clear previous log
    try {
      fs.writeFileSync(logPath, `Backend started at ${new Date().toISOString()}\n`);
    } catch (e) {
      this._log(`Could not create log file: ${e.message}`);
    }
    
    // Set environment variables
    const env = {
      ...process.env,
      ELECTRON_RESOURCES_PATH: this.resourcesPath,
    };
    
    try {
      this.backendProcess = spawn(this.backendPath, [], {
        env,
        stdio: ['ignore', 'pipe', 'pipe'],
        cwd: path.dirname(this.backendPath), // Set working directory to backend folder
      });
      
      this._log(`Backend process spawned with PID: ${this.backendProcess.pid}`);
      
      // Handle stdout - log to file and console
      this.backendProcess.stdout.on('data', (data) => {
        const msg = data.toString().trim();
        this._log(`[Backend] ${msg}`);
        try {
          fs.appendFileSync(logPath, `[STDOUT] ${msg}\n`);
        } catch (e) { /* ignore */ }
      });
      
      // Handle stderr - log to file and console
      this.backendProcess.stderr.on('data', (data) => {
        const msg = data.toString().trim();
        this._log(`[Backend Error] ${msg}`, 'error');
        try {
          fs.appendFileSync(logPath, `[STDERR] ${msg}\n`);
        } catch (e) { /* ignore */ }
      });
      
      // Handle process exit
      this.backendProcess.on('close', (code) => {
        this._log(`Backend process exited with code ${code}`);
        try {
          fs.appendFileSync(logPath, `[EXIT] Process exited with code ${code}\n`);
        } catch (e) { /* ignore */ }
        this._handleBackendExit(code);
      });
      
      // Handle spawn error
      this.backendProcess.on('error', (error) => {
        this._log(`Backend spawn error: ${error.message}`, 'error');
        try {
          fs.appendFileSync(logPath, `[ERROR] Spawn error: ${error.message}\n`);
        } catch (e) { /* ignore */ }
        this._handleBackendExit(-1);
      });
      
      // Give the backend a moment to start
      await this._sleep(500);
      
      // Check if process is still running
      if (this.backendProcess.exitCode !== null) {
        throw new Error(`Backend process exited immediately with code ${this.backendProcess.exitCode}`);
      }
      
      this._log('Backend process started successfully');
      
    } catch (error) {
      this._log(`Failed to spawn backend: ${error.message}`, 'error');
      throw error;
    }
  }

  /**
   * Wait for backend to be ready
   * @returns {Promise<boolean>}
   */
  async waitForBackend() {
    this._setPhase(StartupPhase.WAITING_FOR_BACKEND);
    this._log('Waiting for backend to be ready...');
    
    // Check if backend process is still running before polling
    if (!this.isDev && this.backendProcess) {
      if (this.backendProcess.exitCode !== null) {
        this._log(`Backend process already exited with code ${this.backendProcess.exitCode}`, 'error');
        return false;
      }
    }
    
    const result = await this.healthPoller.waitForReady();
    
    this.lastHealthResponse = result.response;
    
    if (result.ready) {
      this._log(`Backend ready after ${result.attempts} attempts (${result.totalTimeMs}ms)`);
      this._setPhase(StartupPhase.READY);
      return true;
    }
    
    // Check if backend crashed during polling
    if (!this.isDev && this.backendProcess && this.backendProcess.exitCode !== null) {
      this._log(`Backend process crashed during startup with code ${this.backendProcess.exitCode}`, 'error');
    }
    
    this._log(`Backend not ready: ${result.error}`, 'error');
    return false;
  }

  /**
   * Handle backend crash and attempt restart
   * @returns {Promise<boolean>} Whether recovery was successful
   */
  async handleBackendCrash() {
    if (this.phase === StartupPhase.RECOVERING) {
      this._log('Already recovering, skipping');
      return false;
    }
    
    this._setPhase(StartupPhase.RECOVERING);
    this.restartCount++;
    
    this._log(`Backend crashed, attempting restart (${this.restartCount}/${this.config.maxRestartAttempts})`);
    
    if (this.restartCount > this.config.maxRestartAttempts) {
      this._log('Max restart attempts exceeded', 'error');
      this._setPhase(StartupPhase.ERROR);
      return false;
    }
    
    try {
      // Kill any orphaned processes
      this._killOrphanedProcesses();
      
      // Wait a moment before restarting
      await this._sleep(1000);
      
      // Restart backend
      await this.startBackend();
      
      // Wait for ready
      const ready = await this.waitForBackend();
      
      if (ready) {
        this._log('Backend recovered successfully');
        this._setPhase(StartupPhase.READY);
        return true;
      }
      
      return false;
      
    } catch (error) {
      this._log(`Recovery failed: ${error.message}`, 'error');
      this._setPhase(StartupPhase.ERROR);
      return false;
    }
  }

  /**
   * Get current startup status
   * @returns {{phase: string, progress: number, message: string, isDegraded: boolean}}
   */
  getStatus() {
    const phaseMessages = {
      [StartupPhase.IDLE]: 'Initializing...',
      [StartupPhase.SPAWNING_BACKEND]: 'Starting backend service...',
      [StartupPhase.WAITING_FOR_BACKEND]: 'Connecting to backend...',
      [StartupPhase.LOADING_FRONTEND]: 'Loading application...',
      [StartupPhase.READY]: 'Ready',
      [StartupPhase.ERROR]: 'Startup failed',
      [StartupPhase.RECOVERING]: 'Reconnecting...',
    };
    
    const phaseProgress = {
      [StartupPhase.IDLE]: 0,
      [StartupPhase.SPAWNING_BACKEND]: 20,
      [StartupPhase.WAITING_FOR_BACKEND]: 50,
      [StartupPhase.LOADING_FRONTEND]: 80,
      [StartupPhase.READY]: 100,
      [StartupPhase.ERROR]: 0,
      [StartupPhase.RECOVERING]: 30,
    };
    
    return {
      phase: this.phase,
      progress: phaseProgress[this.phase] || 0,
      message: phaseMessages[this.phase] || 'Unknown',
      isDegraded: this.lastHealthResponse?.is_degraded || false,
      degradedFeatures: this.lastHealthResponse?.degraded_features || [],
      restartCount: this.restartCount,
    };
  }

  /**
   * Stop the orchestrator and cleanup
   */
  async stop() {
    this._log('Stopping orchestrator...');
    
    // Stop crash detection
    if (this.crashDetectionInterval) {
      clearInterval(this.crashDetectionInterval);
      this.crashDetectionInterval = null;
    }
    
    // Kill backend process
    await this.killBackend();
    
    this._setPhase(StartupPhase.IDLE);
  }

  /**
   * Kill the backend process
   */
  async killBackend() {
    if (!this.backendProcess) {
      return;
    }
    
    const pid = this.backendProcess.pid;
    this._log(`Killing backend process (PID: ${pid})`);
    
    try {
      if (process.platform === 'win32') {
        execSync(`taskkill /F /T /PID ${pid}`, { stdio: 'ignore' });
      } else {
        this.backendProcess.kill('SIGTERM');
        await this._sleep(3000);
        try {
          process.kill(pid, 0);
          this.backendProcess.kill('SIGKILL');
        } catch (e) {
          // Process already dead
        }
      }
    } catch (error) {
      this._log(`Error killing backend: ${error.message}`);
    }
    
    this.backendProcess = null;
  }

  /**
   * Kill any orphaned backend processes
   * @private
   */
  _killOrphanedProcesses() {
    try {
      if (process.platform === 'win32') {
        execSync('taskkill /F /IM nexus-installer-backend.exe /T', { stdio: 'ignore' });
      } else {
        execSync('pkill -f nexus-installer-backend', { stdio: 'ignore' });
      }
    } catch (error) {
      // No processes found - this is fine
    }
  }

  /**
   * Start crash detection monitoring
   * @private
   */
  _startCrashDetection() {
    if (this.isDev) {
      return; // Don't monitor in dev mode
    }
    
    this.crashDetectionInterval = setInterval(() => {
      if (this.backendProcess && this.backendProcess.exitCode !== null) {
        this._log('Crash detected via exit code check');
        this.handleBackendCrash();
      }
    }, this.config.crashDetectionIntervalMs);
  }

  /**
   * Handle backend process exit
   * @private
   */
  _handleBackendExit(code) {
    if (this.phase === StartupPhase.READY && code !== 0) {
      this._log(`Backend crashed with code ${code}`);
      this.handleBackendCrash();
    }
  }

  /**
   * Handle health poll attempt
   * @private
   */
  _handleHealthAttempt(info) {
    // Update progress based on attempts - only send updates every 10% to avoid flooding
    const progress = Math.min(20 + Math.floor((info.attempt / info.maxAttempts) * 60), 80);
    const roundedProgress = Math.floor(progress / 10) * 10;  // Round to nearest 10%
    
    // Only send update if progress changed significantly (every 10%)
    if (roundedProgress !== this.lastSentProgress) {
      this.lastSentProgress = roundedProgress;
      this.onStatusChange({
        ...this.getStatus(),
        progress: roundedProgress,
        message: 'Starting the services...',
      });
    }
  }

  /**
   * Set the current phase and notify listeners
   * @private
   */
  _setPhase(phase) {
    this.phase = phase;
    this.onStatusChange(this.getStatus());
  }

  /**
   * Log a message
   * @private
   */
  _log(message, level = 'info') {
    const prefix = '[StartupOrchestrator]';
    if (level === 'error') {
      console.error(`${prefix} ${message}`);
    } else {
      console.log(`${prefix} ${message}`);
    }
    this.onLog(message, level);
  }

  /**
   * Sleep for specified milliseconds
   * @private
   */
  _sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}

/**
 * Create a startup orchestrator with default configuration
 * @param {Object} options - Override options
 * @returns {StartupOrchestrator}
 */
function createStartupOrchestrator(options = {}) {
  return new StartupOrchestrator(options);
}

module.exports = {
  StartupOrchestrator,
  createStartupOrchestrator,
  StartupPhase,
  DEFAULT_CONFIG,
};
