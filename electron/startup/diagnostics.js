/**
 * Startup Diagnostics Module
 * 
 * Logs timestamps for each startup phase, system information,
 * and detailed error traces for troubleshooting.
 * 
 * Feature: startup-health-check
 * Requirements: 8.1, 8.3, 8.4, 8.6
 */

const fs = require('fs');
const path = require('path');
const os = require('os');

/**
 * Log levels
 */
const LogLevel = {
  DEBUG: 0,
  INFO: 1,
  WARN: 2,
  ERROR: 3,
};

/**
 * StartupDiagnostics class
 * Provides detailed logging for startup process
 */
class StartupDiagnostics {
  constructor(options = {}) {
    this.logFile = options.logFile || this.getDefaultLogPath();
    this.logLevel = options.logLevel || LogLevel.INFO;
    this.enabled = options.enabled !== false;
    this.phases = new Map();
    this.startTime = null;
    this.systemInfo = null;
    this.logs = [];
    this.maxLogEntries = options.maxLogEntries || 1000;
  }

  /**
   * Get default log file path
   */
  getDefaultLogPath() {
    try {
      const { app } = require('electron');
      if (app) {
        return path.join(app.getPath('userData'), 'logs', 'startup.log');
      }
    } catch (e) {
      // Not in Electron context
    }
    return path.join(process.cwd(), 'startup.log');
  }

  /**
   * Initialize diagnostics and log system info
   */
  initialize() {
    this.startTime = Date.now();
    this.systemInfo = this.collectSystemInfo();
    
    this.ensureLogDirectory();
    
    this.log('INFO', '='.repeat(60));
    this.log('INFO', `Startup Diagnostics Initialized`);
    this.log('INFO', `Timestamp: ${new Date().toISOString()}`);
    this.log('INFO', '='.repeat(60));
    this.logSystemInfo();
  }

  /**
   * Collect system information
   */
  collectSystemInfo() {
    return {
      platform: os.platform(),
      arch: os.arch(),
      release: os.release(),
      hostname: os.hostname(),
      cpus: os.cpus().length,
      totalMemory: os.totalmem(),
      freeMemory: os.freemem(),
      uptime: os.uptime(),
      nodeVersion: process.version,
      electronVersion: process.versions.electron || 'N/A',
      cwd: process.cwd(),
      pid: process.pid,
    };
  }

  /**
   * Log system information
   */
  logSystemInfo() {
    if (!this.systemInfo) return;
    
    this.log('INFO', 'System Information:');
    this.log('INFO', `  Platform: ${this.systemInfo.platform} (${this.systemInfo.arch})`);
    this.log('INFO', `  OS Release: ${this.systemInfo.release}`);
    this.log('INFO', `  CPUs: ${this.systemInfo.cpus}`);
    this.log('INFO', `  Total Memory: ${this.formatBytes(this.systemInfo.totalMemory)}`);
    this.log('INFO', `  Free Memory: ${this.formatBytes(this.systemInfo.freeMemory)}`);
    this.log('INFO', `  Node Version: ${this.systemInfo.nodeVersion}`);
    this.log('INFO', `  Electron Version: ${this.systemInfo.electronVersion}`);
    this.log('INFO', `  Process ID: ${this.systemInfo.pid}`);
  }

  /**
   * Start tracking a phase
   * @param {string} phaseName - Name of the phase
   * @param {string} description - Phase description
   */
  startPhase(phaseName, description = '') {
    const phase = {
      name: phaseName,
      description,
      startTime: Date.now(),
      endTime: null,
      duration: null,
      status: 'running',
      error: null,
    };
    
    this.phases.set(phaseName, phase);
    this.log('INFO', `[PHASE START] ${phaseName}${description ? ': ' + description : ''}`);
  }

  /**
   * End tracking a phase
   * @param {string} phaseName - Name of the phase
   * @param {string} status - Final status ('success', 'failed', 'skipped')
   * @param {Error} error - Optional error if failed
   */
  endPhase(phaseName, status = 'success', error = null) {
    const phase = this.phases.get(phaseName);
    if (!phase) {
      this.log('WARN', `[PHASE END] Unknown phase: ${phaseName}`);
      return;
    }
    
    phase.endTime = Date.now();
    phase.duration = phase.endTime - phase.startTime;
    phase.status = status;
    phase.error = error;
    
    const durationStr = `${phase.duration}ms`;
    
    if (status === 'success') {
      this.log('INFO', `[PHASE END] ${phaseName} completed in ${durationStr}`);
    } else if (status === 'failed') {
      this.log('ERROR', `[PHASE END] ${phaseName} failed after ${durationStr}`);
      if (error) {
        this.logError(error);
      }
    } else {
      this.log('WARN', `[PHASE END] ${phaseName} ${status} after ${durationStr}`);
    }
  }

  /**
   * Log a message
   * @param {string} level - Log level
   * @param {string} message - Log message
   */
  log(level, message) {
    if (!this.enabled) return;
    
    const levelNum = LogLevel[level] ?? LogLevel.INFO;
    if (levelNum < this.logLevel) return;
    
    const timestamp = new Date().toISOString();
    const elapsed = this.startTime ? `+${Date.now() - this.startTime}ms` : '';
    const logEntry = `[${timestamp}] [${level}] ${elapsed} ${message}`;
    
    // Store in memory
    this.logs.push(logEntry);
    if (this.logs.length > this.maxLogEntries) {
      this.logs.shift();
    }
    
    // Write to file
    this.writeToFile(logEntry);
    
    // Also log to console in development
    if (process.env.NODE_ENV !== 'production') {
      console.log(logEntry);
    }
  }

  /**
   * Log an error with full stack trace
   * @param {Error} error - Error to log
   */
  logError(error) {
    this.log('ERROR', `Error: ${error.message}`);
    if (error.stack) {
      const stackLines = error.stack.split('\n');
      stackLines.forEach(line => {
        this.log('ERROR', `  ${line.trim()}`);
      });
    }
    if (error.cause) {
      this.log('ERROR', `Caused by: ${error.cause}`);
    }
  }

  /**
   * Log a health check result
   * @param {Object} result - Health check result
   */
  logHealthCheck(result) {
    this.log('DEBUG', `Health check: ready=${result.ready}, phase=${result.phase}`);
    if (result.components) {
      result.components.forEach(comp => {
        this.log('DEBUG', `  Component ${comp.name}: ${comp.status}`);
      });
    }
  }

  /**
   * Log backend process status
   * @param {string} status - Process status
   * @param {Object} details - Additional details
   */
  logBackendStatus(status, details = {}) {
    this.log('INFO', `Backend status: ${status}`);
    if (details.pid) {
      this.log('INFO', `  PID: ${details.pid}`);
    }
    if (details.port) {
      this.log('INFO', `  Port: ${details.port}`);
    }
    if (details.exitCode !== undefined) {
      this.log('INFO', `  Exit code: ${details.exitCode}`);
    }
  }

  /**
   * Ensure log directory exists
   */
  ensureLogDirectory() {
    try {
      const dir = path.dirname(this.logFile);
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }
    } catch (error) {
      console.error('Failed to create log directory:', error.message);
    }
  }

  /**
   * Write to log file
   * @param {string} entry - Log entry
   */
  writeToFile(entry) {
    try {
      fs.appendFileSync(this.logFile, entry + '\n');
    } catch (error) {
      // Silently fail file writes
    }
  }

  /**
   * Get startup summary
   * @returns {Object} Summary of startup process
   */
  getSummary() {
    const totalDuration = this.startTime ? Date.now() - this.startTime : 0;
    const phases = Array.from(this.phases.values());
    
    return {
      totalDuration,
      startTime: this.startTime ? new Date(this.startTime).toISOString() : null,
      phases: phases.map(p => ({
        name: p.name,
        duration: p.duration,
        status: p.status,
        error: p.error?.message,
      })),
      systemInfo: this.systemInfo,
      successfulPhases: phases.filter(p => p.status === 'success').length,
      failedPhases: phases.filter(p => p.status === 'failed').length,
    };
  }

  /**
   * Get recent logs
   * @param {number} count - Number of recent logs to return
   * @returns {string[]} Recent log entries
   */
  getRecentLogs(count = 50) {
    return this.logs.slice(-count);
  }

  /**
   * Format bytes to human readable
   * @param {number} bytes - Bytes to format
   * @returns {string} Formatted string
   */
  formatBytes(bytes) {
    const units = ['B', 'KB', 'MB', 'GB'];
    let unitIndex = 0;
    let value = bytes;
    
    while (value >= 1024 && unitIndex < units.length - 1) {
      value /= 1024;
      unitIndex++;
    }
    
    return `${value.toFixed(1)} ${units[unitIndex]}`;
  }

  /**
   * Finalize diagnostics
   */
  finalize() {
    const summary = this.getSummary();
    
    this.log('INFO', '='.repeat(60));
    this.log('INFO', 'Startup Complete');
    this.log('INFO', `Total Duration: ${summary.totalDuration}ms`);
    this.log('INFO', `Successful Phases: ${summary.successfulPhases}`);
    this.log('INFO', `Failed Phases: ${summary.failedPhases}`);
    this.log('INFO', '='.repeat(60));
    
    return summary;
  }
}

/**
 * Create a diagnostics instance
 * @param {Object} options - Configuration options
 * @returns {StartupDiagnostics} Diagnostics instance
 */
function createDiagnostics(options = {}) {
  return new StartupDiagnostics(options);
}

// Default instance
const defaultDiagnostics = new StartupDiagnostics();

module.exports = {
  StartupDiagnostics,
  createDiagnostics,
  LogLevel,
  defaultDiagnostics,
};
