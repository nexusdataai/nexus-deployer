/**
 * Health Poller for Backend Readiness Checks
 * 
 * Polls the backend health endpoint with exponential backoff until
 * the service reports ready or timeout is reached.
 * 
 * Feature: startup-health-check
 * Requirements: 2.2, 2.3, 2.5
 */

const http = require('http');

/**
 * Default configuration for health polling
 */
const DEFAULT_CONFIG = {
  baseUrl: 'http://127.0.0.1:8001',  // Use IPv4 explicitly, not 'localhost'
  healthEndpoint: '/api/health/ready',
  maxAttempts: 300,        // 30 seconds at minimum delay
  initialDelayMs: 100,     // Start with 100ms delay
  maxDelayMs: 2000,        // Cap at 2 seconds
  backoffMultiplier: 1.5,  // Exponential backoff factor
  requestTimeoutMs: 5000,  // Timeout for each request
};

/**
 * Health check result
 * @typedef {Object} HealthCheckResult
 * @property {boolean} ready - Whether the backend is ready
 * @property {Object} [response] - The health check response data
 * @property {string} [error] - Error message if check failed
 * @property {number} attempts - Number of attempts made
 * @property {number} totalTimeMs - Total time spent polling
 */

/**
 * Health Poller class for checking backend readiness
 */
class HealthPoller {
  /**
   * Create a new HealthPoller instance
   * @param {Object} options - Configuration options
   * @param {string} [options.baseUrl] - Base URL of the backend
   * @param {string} [options.healthEndpoint] - Health check endpoint path
   * @param {number} [options.maxAttempts] - Maximum polling attempts
   * @param {number} [options.initialDelayMs] - Initial delay between attempts
   * @param {number} [options.maxDelayMs] - Maximum delay between attempts
   * @param {number} [options.backoffMultiplier] - Exponential backoff multiplier
   * @param {number} [options.requestTimeoutMs] - Timeout for each request
   * @param {Function} [options.onAttempt] - Callback for each attempt
   */
  constructor(options = {}) {
    this.config = { ...DEFAULT_CONFIG, ...options };
    this.onAttempt = options.onAttempt || (() => {});
    this.lastLoggedAttempt = 0;  // Track last logged attempt to reduce log spam
  }

  /**
   * Calculate delay for a given attempt using exponential backoff
   * @param {number} attempt - Current attempt number (0-indexed)
   * @returns {number} Delay in milliseconds
   */
  calculateDelay(attempt) {
    const delay = this.config.initialDelayMs * Math.pow(this.config.backoffMultiplier, attempt);
    return Math.min(Math.round(delay), this.config.maxDelayMs);
  }

  /**
   * Perform a single health check
   * @returns {Promise<{ready: boolean, response?: Object, error?: string}>}
   */
  async checkHealth() {
    return new Promise((resolve) => {
      const url = `${this.config.baseUrl}${this.config.healthEndpoint}`;
      
      const req = http.get(url, { timeout: this.config.requestTimeoutMs }, (res) => {
        let data = '';
        
        res.on('data', (chunk) => {
          data += chunk;
        });
        
        res.on('end', () => {
          try {
            const response = JSON.parse(data);
            resolve({
              ready: response.ready === true,
              response,
              statusCode: res.statusCode,
            });
          } catch (e) {
            resolve({
              ready: false,
              error: `Invalid JSON response: ${e.message}`,
              statusCode: res.statusCode,
            });
          }
        });
      });

      req.on('error', (error) => {
        resolve({
          ready: false,
          error: error.message,
        });
      });

      req.on('timeout', () => {
        req.destroy();
        resolve({
          ready: false,
          error: 'Request timeout',
        });
      });
    });
  }

  /**
   * Poll until backend is ready or max attempts reached
   * @returns {Promise<HealthCheckResult>}
   */
  async waitForReady() {
    const startTime = Date.now();
    let attempts = 0;
    let lastError = null;
    let lastResponse = null;

    console.log(`[HealthPoller] Starting health polling (max ${this.config.maxAttempts} attempts)`);

    while (attempts < this.config.maxAttempts) {
      const delay = this.calculateDelay(attempts);
      
      // Only log every 10 attempts to reduce spam
      const shouldLog = attempts === 0 || (attempts + 1) % 10 === 0;
      if (shouldLog) {
        console.log(`[HealthPoller] Attempt ${attempts + 1}/${this.config.maxAttempts} (delay: ${delay}ms)`);
      }
      
      // Notify callback (throttled in orchestrator)
      this.onAttempt({
        attempt: attempts + 1,
        maxAttempts: this.config.maxAttempts,
        delay,
        elapsedMs: Date.now() - startTime,
      });

      // Perform health check
      const result = await this.checkHealth();
      lastResponse = result.response;
      lastError = result.error;

      if (result.ready) {
        const totalTimeMs = Date.now() - startTime;
        console.log(`[HealthPoller] Backend ready after ${attempts + 1} attempts (${totalTimeMs}ms)`);
        
        return {
          ready: true,
          response: result.response,
          attempts: attempts + 1,
          totalTimeMs,
        };
      }

      // Log status if available
      if (result.response) {
        console.log(`[HealthPoller] Not ready: phase=${result.response.phase}, reason=${result.response.reason}`);
      } else if (result.error) {
        console.log(`[HealthPoller] Check failed: ${result.error}`);
      }

      attempts++;

      // Wait before next attempt (unless this was the last attempt)
      if (attempts < this.config.maxAttempts) {
        await this.sleep(delay);
      }
    }

    // Max attempts reached
    const totalTimeMs = Date.now() - startTime;
    console.error(`[HealthPoller] Backend not ready after ${attempts} attempts (${totalTimeMs}ms)`);

    return {
      ready: false,
      response: lastResponse,
      error: lastError || 'Max attempts reached',
      attempts,
      totalTimeMs,
    };
  }

  /**
   * Sleep for specified milliseconds
   * @param {number} ms - Milliseconds to sleep
   * @returns {Promise<void>}
   */
  sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  /**
   * Get the current configuration
   * @returns {Object} Current configuration
   */
  getConfig() {
    return { ...this.config };
  }
}

/**
 * Create a health poller with default configuration
 * @param {Object} options - Override options
 * @returns {HealthPoller}
 */
function createHealthPoller(options = {}) {
  return new HealthPoller(options);
}

module.exports = {
  HealthPoller,
  createHealthPoller,
  DEFAULT_CONFIG,
};
