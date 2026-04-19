/**
 * Startup Configuration Module
 * 
 * Loads and manages startup configuration from environment variables
 * and configuration files with sensible defaults.
 * 
 * Feature: startup-health-check
 * Requirements: 7.1, 7.2, 7.4, 7.5, 7.6
 */

const fs = require('fs');
const path = require('path');

/**
 * Default startup configuration values
 */
const DEFAULT_CONFIG = {
  // Health check settings - Use 127.0.0.1 instead of localhost to avoid IPv6 issues
  healthCheckUrl: 'http://127.0.0.1:8001/api/health/ready',
  healthCheckTimeoutMs: 60000,
  healthCheckIntervalMs: 1000,
  healthCheckMaxRetries: 60,
  
  // Backoff settings
  initialBackoffMs: 500,
  maxBackoffMs: 5000,
  backoffMultiplier: 1.5,
  
  // Backend settings
  backendStartTimeoutMs: 30000,
  backendPort: 8001,
  backendHost: '127.0.0.1',
  
  // Recovery settings
  maxRestartAttempts: 3,
  restartDelayMs: 2000,
  
  // Logging settings
  enableStartupLogging: true,
  startupLogFile: 'startup.log',
  logLevel: 'info',
  
  // Feature flags
  enableDegradedMode: true,
  showLoadingScreen: true,
  enableHealthMonitoring: true,
};

/**
 * Environment variable mappings
 */
const ENV_MAPPINGS = {
  STARTUP_HEALTH_CHECK_URL: 'healthCheckUrl',
  STARTUP_HEALTH_CHECK_TIMEOUT_MS: 'healthCheckTimeoutMs',
  STARTUP_HEALTH_CHECK_INTERVAL_MS: 'healthCheckIntervalMs',
  STARTUP_HEALTH_CHECK_MAX_RETRIES: 'healthCheckMaxRetries',
  STARTUP_INITIAL_BACKOFF_MS: 'initialBackoffMs',
  STARTUP_MAX_BACKOFF_MS: 'maxBackoffMs',
  STARTUP_BACKOFF_MULTIPLIER: 'backoffMultiplier',
  STARTUP_BACKEND_TIMEOUT_MS: 'backendStartTimeoutMs',
  STARTUP_BACKEND_PORT: 'backendPort',
  STARTUP_BACKEND_HOST: 'backendHost',
  STARTUP_MAX_RESTART_ATTEMPTS: 'maxRestartAttempts',
  STARTUP_RESTART_DELAY_MS: 'restartDelayMs',
  STARTUP_ENABLE_LOGGING: 'enableStartupLogging',
  STARTUP_LOG_FILE: 'startupLogFile',
  STARTUP_LOG_LEVEL: 'logLevel',
  STARTUP_ENABLE_DEGRADED_MODE: 'enableDegradedMode',
  STARTUP_SHOW_LOADING_SCREEN: 'showLoadingScreen',
  STARTUP_ENABLE_HEALTH_MONITORING: 'enableHealthMonitoring',
};

/**
 * Parse a value based on expected type
 * @param {string} value - Raw string value
 * @param {any} defaultValue - Default value to infer type from
 * @returns {any} Parsed value
 */
function parseValue(value, defaultValue) {
  if (value === undefined || value === null || value === '') {
    return defaultValue;
  }

  const type = typeof defaultValue;
  
  switch (type) {
    case 'number':
      const num = parseFloat(value);
      return isNaN(num) ? defaultValue : num;
    case 'boolean':
      return value.toLowerCase() === 'true' || value === '1';
    case 'string':
      return value;
    default:
      return value;
  }
}

/**
 * Load configuration from environment variables
 * @returns {Object} Configuration from environment
 */
function loadFromEnvironment() {
  const config = {};
  
  for (const [envKey, configKey] of Object.entries(ENV_MAPPINGS)) {
    const envValue = process.env[envKey];
    if (envValue !== undefined) {
      config[configKey] = parseValue(envValue, DEFAULT_CONFIG[configKey]);
    }
  }
  
  return config;
}

/**
 * Load configuration from a JSON file
 * @param {string} filePath - Path to configuration file
 * @returns {Object} Configuration from file
 */
function loadFromFile(filePath) {
  try {
    if (!fs.existsSync(filePath)) {
      return {};
    }
    
    const content = fs.readFileSync(filePath, 'utf8');
    const parsed = JSON.parse(content);
    
    // Validate and filter to known keys
    const config = {};
    for (const key of Object.keys(DEFAULT_CONFIG)) {
      if (parsed[key] !== undefined) {
        config[key] = parseValue(String(parsed[key]), DEFAULT_CONFIG[key]);
      }
    }
    
    return config;
  } catch (error) {
    console.warn(`[StartupConfig] Failed to load config from ${filePath}:`, error.message);
    return {};
  }
}

/**
 * Get the default config file path
 * @returns {string} Path to config file
 */
function getDefaultConfigPath() {
  // Check for app data directory in Electron
  const { app } = require('electron');
  if (app) {
    return path.join(app.getPath('userData'), 'startup-config.json');
  }
  
  // Fallback to current directory
  return path.join(process.cwd(), 'startup-config.json');
}

/**
 * StartupConfig class
 * Manages startup configuration with defaults, file, and environment overrides
 */
class StartupConfig {
  constructor(options = {}) {
    this.configPath = options.configPath || getDefaultConfigPath();
    this.config = { ...DEFAULT_CONFIG };
    this.loaded = false;
  }

  /**
   * Load configuration from all sources
   * Priority: defaults < file < environment
   */
  load() {
    // Start with defaults
    this.config = { ...DEFAULT_CONFIG };
    
    // Override with file config
    const fileConfig = loadFromFile(this.configPath);
    Object.assign(this.config, fileConfig);
    
    // Override with environment variables
    const envConfig = loadFromEnvironment();
    Object.assign(this.config, envConfig);
    
    this.loaded = true;
    return this.config;
  }

  /**
   * Get a configuration value
   * @param {string} key - Configuration key
   * @returns {any} Configuration value
   */
  get(key) {
    if (!this.loaded) {
      this.load();
    }
    return this.config[key];
  }

  /**
   * Get all configuration values
   * @returns {Object} Full configuration
   */
  getAll() {
    if (!this.loaded) {
      this.load();
    }
    return { ...this.config };
  }

  /**
   * Set a configuration value (runtime only)
   * @param {string} key - Configuration key
   * @param {any} value - Configuration value
   */
  set(key, value) {
    if (key in DEFAULT_CONFIG) {
      this.config[key] = parseValue(String(value), DEFAULT_CONFIG[key]);
    }
  }

  /**
   * Save current configuration to file
   */
  save() {
    try {
      const dir = path.dirname(this.configPath);
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }
      
      fs.writeFileSync(this.configPath, JSON.stringify(this.config, null, 2));
      return true;
    } catch (error) {
      console.error('[StartupConfig] Failed to save config:', error.message);
      return false;
    }
  }

  /**
   * Reset to default configuration
   */
  reset() {
    this.config = { ...DEFAULT_CONFIG };
  }

  /**
   * Validate configuration values
   * @returns {Object} Validation result with isValid and errors
   */
  validate() {
    const errors = [];
    
    if (this.config.healthCheckTimeoutMs < 1000) {
      errors.push('healthCheckTimeoutMs must be at least 1000ms');
    }
    
    if (this.config.healthCheckIntervalMs < 100) {
      errors.push('healthCheckIntervalMs must be at least 100ms');
    }
    
    if (this.config.backoffMultiplier < 1) {
      errors.push('backoffMultiplier must be at least 1');
    }
    
    if (this.config.maxRestartAttempts < 0) {
      errors.push('maxRestartAttempts must be non-negative');
    }
    
    if (this.config.backendPort < 1 || this.config.backendPort > 65535) {
      errors.push('backendPort must be between 1 and 65535');
    }
    
    return {
      isValid: errors.length === 0,
      errors,
    };
  }
}

/**
 * Get default configuration values
 * @returns {Object} Default configuration
 */
function getDefaults() {
  return { ...DEFAULT_CONFIG };
}

/**
 * Create a startup config instance
 * @param {Object} options - Configuration options
 * @returns {StartupConfig} Config instance
 */
function createStartupConfig(options = {}) {
  return new StartupConfig(options);
}

// Default instance
const defaultConfig = new StartupConfig();

module.exports = {
  StartupConfig,
  createStartupConfig,
  getDefaults,
  DEFAULT_CONFIG,
  defaultConfig,
};
