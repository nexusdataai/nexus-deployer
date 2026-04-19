/**
 * Property-based tests for API Retry Layer
 * Feature: startup-health-check
 * Property 4: Retry Exhaustion Behavior
 * Validates: Requirements 4.4, 4.5
 */

import { describe, test, expect, vi } from 'vitest';
import { ApiRetryLayer, createApiRetryLayer, withRetry } from './api-retry';

// ============================================
// Property 4: Retry Exhaustion Behavior
// Validates: Requirements 4.4, 4.5
// ============================================

describe('Property 4: Retry Exhaustion Behavior', () => {
  describe('Retry Count', () => {
    test('retries exactly maxRetries times before failing', async () => {
      const retryLayer = new ApiRetryLayer({
        maxRetries: 3,
        initialDelayMs: 10,
        maxDelayMs: 50,
      });

      let callCount = 0;
      const failingRequest = async () => {
        callCount++;
        throw new Error('Network error');
      };

      const result = await retryLayer.executeWithRetry(failingRequest);

      expect(result.success).toBe(false);
      expect(callCount).toBe(4); // Initial + 3 retries
      expect(result.attempts).toBe(4);
    });

    test('stops retrying on success', async () => {
      const retryLayer = new ApiRetryLayer({
        maxRetries: 5,
        initialDelayMs: 10,
      });

      let callCount = 0;
      const eventuallySucceeds = async () => {
        callCount++;
        if (callCount < 3) {
          throw new Error('Network error');
        }
        return 'success';
      };

      const result = await retryLayer.executeWithRetry(eventuallySucceeds);

      expect(result.success).toBe(true);
      expect(result.data).toBe('success');
      expect(callCount).toBe(3);
      expect(result.attempts).toBe(3);
    });

    test.each([0, 1, 2, 3, 5])('respects maxRetries=%i configuration', async (maxRetries) => {
      const retryLayer = new ApiRetryLayer({
        maxRetries,
        initialDelayMs: 10,
        maxDelayMs: 20,
      });

      let callCount = 0;
      const failingRequest = async () => {
        callCount++;
        throw new Error('Network error');
      };

      await retryLayer.executeWithRetry(failingRequest);

      expect(callCount).toBe(maxRetries + 1);
    });
  });

  describe('Error Handling', () => {
    test('returns error after all retries exhausted', async () => {
      const retryLayer = new ApiRetryLayer({
        maxRetries: 2,
        initialDelayMs: 10,
      });

      const errorMessage = 'Connection refused';
      const failingRequest = async () => {
        throw new Error(errorMessage);
      };

      const result = await retryLayer.executeWithRetry(failingRequest);

      expect(result.success).toBe(false);
      expect(result.error).toBeDefined();
      expect(result.error?.message).toBe(errorMessage);
    });

    test('preserves original error after retries', async () => {
      const retryLayer = new ApiRetryLayer({
        maxRetries: 2,
        initialDelayMs: 10,
      });

      const customError = new Error('Custom error');
      const failingRequest = async () => {
        throw customError;
      };

      const result = await retryLayer.executeWithRetry(failingRequest);

      expect(result.error).toBe(customError);
    });
  });

  describe('Callback Notifications', () => {
    test('calls onRetry callback for each retry attempt', async () => {
      const retryLayer = new ApiRetryLayer({
        maxRetries: 3,
        initialDelayMs: 10,
        maxDelayMs: 50,
      });

      const retryInfos: Array<{ attempt: number; delay: number }> = [];
      const onRetry = vi.fn((info) => {
        retryInfos.push({ attempt: info.attempt, delay: info.delay });
      });

      const failingRequest = async () => {
        throw new Error('Network error');
      };

      await retryLayer.executeWithRetry(failingRequest, onRetry);

      expect(onRetry).toHaveBeenCalledTimes(3);
      expect(retryInfos[0].attempt).toBe(1);
      expect(retryInfos[1].attempt).toBe(2);
      expect(retryInfos[2].attempt).toBe(3);
    });

    test('onRetry receives error information', async () => {
      const retryLayer = new ApiRetryLayer({
        maxRetries: 1,
        initialDelayMs: 10,
      });

      const errorMessage = 'Test error';
      let receivedError: Error | undefined;
      const onRetry = vi.fn((info) => {
        receivedError = info.error;
      });

      const failingRequest = async () => {
        throw new Error(errorMessage);
      };

      await retryLayer.executeWithRetry(failingRequest, onRetry);

      expect(receivedError?.message).toBe(errorMessage);
    });
  });
});

describe('Exponential Backoff', () => {
  test('delay follows exponential pattern', () => {
    const retryLayer = new ApiRetryLayer({
      initialDelayMs: 100,
      maxDelayMs: 10000,
      backoffMultiplier: 2,
    });

    expect(retryLayer.calculateDelay(0)).toBe(100);
    expect(retryLayer.calculateDelay(1)).toBe(200);
    expect(retryLayer.calculateDelay(2)).toBe(400);
    expect(retryLayer.calculateDelay(3)).toBe(800);
  });

  test('delay is capped at maxDelayMs', () => {
    const retryLayer = new ApiRetryLayer({
      initialDelayMs: 1000,
      maxDelayMs: 4000,
      backoffMultiplier: 2,
    });

    expect(retryLayer.calculateDelay(0)).toBe(1000);
    expect(retryLayer.calculateDelay(1)).toBe(2000);
    expect(retryLayer.calculateDelay(2)).toBe(4000);
    expect(retryLayer.calculateDelay(3)).toBe(4000); // Capped
    expect(retryLayer.calculateDelay(10)).toBe(4000); // Still capped
  });

  test('delays match requirements: 1s, 2s, 4s', () => {
    const retryLayer = new ApiRetryLayer({
      initialDelayMs: 1000,
      maxDelayMs: 4000,
      backoffMultiplier: 2,
    });

    expect(retryLayer.calculateDelay(0)).toBe(1000);
    expect(retryLayer.calculateDelay(1)).toBe(2000);
    expect(retryLayer.calculateDelay(2)).toBe(4000);
  });
});

describe('Retryable Error Detection', () => {
  test('network errors are retryable', () => {
    const retryLayer = new ApiRetryLayer();

    expect(retryLayer.isRetryableError(new Error('Network error'))).toBe(true);
    expect(retryLayer.isRetryableError(new Error('ECONNREFUSED'))).toBe(true);
    expect(retryLayer.isRetryableError(new Error('ECONNRESET'))).toBe(true);
    expect(retryLayer.isRetryableError(new Error('timeout'))).toBe(true);
    expect(retryLayer.isRetryableError(new Error('Failed to fetch'))).toBe(true);
  });

  test('503 status is retryable', () => {
    const retryLayer = new ApiRetryLayer();

    const axiosError = { response: { status: 503 } };
    expect(retryLayer.isRetryableError(axiosError)).toBe(true);
  });

  test('502 and 504 statuses are retryable', () => {
    const retryLayer = new ApiRetryLayer();

    expect(retryLayer.isRetryableError({ response: { status: 502 } })).toBe(true);
    expect(retryLayer.isRetryableError({ response: { status: 504 } })).toBe(true);
  });

  test('400 and 404 statuses are not retryable', () => {
    const retryLayer = new ApiRetryLayer();

    expect(retryLayer.isRetryableError({ response: { status: 400 } })).toBe(false);
    expect(retryLayer.isRetryableError({ response: { status: 404 } })).toBe(false);
  });

  test('non-network errors are not retryable', () => {
    const retryLayer = new ApiRetryLayer();

    expect(retryLayer.isRetryableError(new Error('Invalid JSON'))).toBe(false);
    expect(retryLayer.isRetryableError(new Error('Validation failed'))).toBe(false);
  });
});

describe('withRetry Helper', () => {
  test('returns data on success', async () => {
    const request = async () => 'test data';
    const result = await withRetry(request);
    expect(result).toBe('test data');
  });

  test('throws error after retries exhausted', async () => {
    const retryLayer = new ApiRetryLayer({
      maxRetries: 1,
      initialDelayMs: 10,
    });

    const request = async () => {
      throw new Error('Network error');
    };

    await expect(withRetry(request, retryLayer)).rejects.toThrow('Network error');
  });
});

describe('Configuration', () => {
  test('uses default configuration', () => {
    const retryLayer = new ApiRetryLayer();
    const config = retryLayer.getConfig();

    expect(config.maxRetries).toBe(3);
    expect(config.initialDelayMs).toBe(1000);
    expect(config.maxDelayMs).toBe(4000);
    expect(config.backoffMultiplier).toBe(2);
  });

  test('allows partial configuration override', () => {
    const retryLayer = new ApiRetryLayer({
      maxRetries: 5,
    });
    const config = retryLayer.getConfig();

    expect(config.maxRetries).toBe(5);
    expect(config.initialDelayMs).toBe(1000); // Default
  });

  test('createApiRetryLayer creates instance with config', () => {
    const retryLayer = createApiRetryLayer({ maxRetries: 10 });
    expect(retryLayer.getConfig().maxRetries).toBe(10);
  });
});

describe('Timing', () => {
  test('tracks total time correctly', async () => {
    const retryLayer = new ApiRetryLayer({
      maxRetries: 2,
      initialDelayMs: 50,
      maxDelayMs: 100,
    });

    const failingRequest = async () => {
      throw new Error('Network error');
    };

    const startTime = Date.now();
    const result = await retryLayer.executeWithRetry(failingRequest);
    const elapsed = Date.now() - startTime;

    expect(result.totalTimeMs).toBeGreaterThan(0);
    expect(result.totalTimeMs).toBeLessThanOrEqual(elapsed + 50);
  });
});
