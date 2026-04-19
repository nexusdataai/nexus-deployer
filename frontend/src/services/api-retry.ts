/**
 * API Retry Layer for Frontend
 * 
 * Provides automatic retry with exponential backoff for API calls.
 * Handles connection errors and 503 responses during startup.
 * 
 * Feature: startup-health-check
 * Requirements: 4.1, 4.2, 4.3, 4.6
 */

export interface RetryConfig {
  maxRetries: number;
  initialDelayMs: number;
  maxDelayMs: number;
  backoffMultiplier: number;
  retryableStatuses: number[];
  retryOnNetworkError: boolean;
}

export interface RetryResult<T> {
  success: boolean;
  data?: T;
  error?: Error;
  attempts: number;
  totalTimeMs: number;
}

export interface RetryAttemptInfo {
  attempt: number;
  maxAttempts: number;
  delay: number;
  error?: Error;
}

const DEFAULT_CONFIG: RetryConfig = {
  maxRetries: 3,
  initialDelayMs: 1000,
  maxDelayMs: 4000,
  backoffMultiplier: 2,
  retryableStatuses: [0, 502, 503, 504],
  retryOnNetworkError: true,
};

/**
 * API Retry Layer class
 * Wraps API calls with automatic retry logic
 */
export class ApiRetryLayer {
  private config: RetryConfig;

  constructor(config?: Partial<RetryConfig>) {
    this.config = { ...DEFAULT_CONFIG, ...config };
  }

  /**
   * Calculate delay for a given attempt using exponential backoff
   * @param attempt - Current attempt number (0-indexed)
   * @returns Delay in milliseconds
   */
  calculateDelay(attempt: number): number {
    const delay = this.config.initialDelayMs * Math.pow(this.config.backoffMultiplier, attempt);
    return Math.min(Math.round(delay), this.config.maxDelayMs);
  }

  /**
   * Check if an error is retryable
   * @param error - The error to check
   * @returns Whether the error should trigger a retry
   */
  isRetryableError(error: unknown): boolean {
    // Network errors (no response)
    if (error instanceof Error) {
      const message = error.message.toLowerCase();
      if (
        message.includes('network') ||
        message.includes('econnrefused') ||
        message.includes('econnreset') ||
        message.includes('timeout') ||
        message.includes('failed to fetch')
      ) {
        return this.config.retryOnNetworkError;
      }
    }

    // Axios-style errors with response
    if (typeof error === 'object' && error !== null && 'response' in error) {
      const axiosError = error as { response?: { status: number } };
      if (axiosError.response?.status) {
        return this.config.retryableStatuses.includes(axiosError.response.status);
      }
    }

    // Status code 0 (network error)
    if (typeof error === 'object' && error !== null && 'status' in error) {
      const statusError = error as { status: number };
      return this.config.retryableStatuses.includes(statusError.status);
    }

    return false;
  }

  /**
   * Execute a request with automatic retry
   * @param request - The request function to execute
   * @param onRetry - Optional callback for each retry attempt
   * @returns The result of the request
   */
  async executeWithRetry<T>(
    request: () => Promise<T>,
    onRetry?: (info: RetryAttemptInfo) => void
  ): Promise<RetryResult<T>> {
    const startTime = Date.now();
    let lastError: Error | undefined;
    let attempts = 0;

    while (attempts <= this.config.maxRetries) {
      try {
        const data = await request();
        return {
          success: true,
          data,
          attempts: attempts + 1,
          totalTimeMs: Date.now() - startTime,
        };
      } catch (error) {
        lastError = error instanceof Error ? error : new Error(String(error));
        attempts++;

        // Check if we should retry
        if (attempts <= this.config.maxRetries && this.isRetryableError(error)) {
          const delay = this.calculateDelay(attempts - 1);
          
          // Notify callback
          if (onRetry) {
            onRetry({
              attempt: attempts,
              maxAttempts: this.config.maxRetries + 1,
              delay,
              error: lastError,
            });
          }

          console.log(
            `[ApiRetry] Attempt ${attempts}/${this.config.maxRetries + 1} failed, ` +
            `retrying in ${delay}ms: ${lastError.message}`
          );

          await this.sleep(delay);
        } else {
          // Not retryable or max retries reached
          break;
        }
      }
    }

    return {
      success: false,
      error: lastError,
      attempts,
      totalTimeMs: Date.now() - startTime,
    };
  }

  /**
   * Sleep for specified milliseconds
   */
  private sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  /**
   * Get the current configuration
   */
  getConfig(): RetryConfig {
    return { ...this.config };
  }
}

/**
 * Create an API retry layer with default configuration
 */
export function createApiRetryLayer(config?: Partial<RetryConfig>): ApiRetryLayer {
  return new ApiRetryLayer(config);
}

/**
 * Default retry layer instance for startup-critical requests
 */
export const startupRetryLayer = new ApiRetryLayer({
  maxRetries: 3,
  initialDelayMs: 1000,
  maxDelayMs: 4000,
  backoffMultiplier: 2,
});

/**
 * Wrap an axios instance with retry logic
 * @param axiosInstance - The axios instance to wrap
 * @param retryLayer - The retry layer to use
 * @returns A wrapped request function
 */
export function withRetry<T>(
  request: () => Promise<T>,
  retryLayer: ApiRetryLayer = startupRetryLayer,
  onRetry?: (info: RetryAttemptInfo) => void
): Promise<T> {
  return retryLayer.executeWithRetry(request, onRetry).then(result => {
    if (result.success && result.data !== undefined) {
      return result.data;
    }
    throw result.error || new Error('Request failed after retries');
  });
}
