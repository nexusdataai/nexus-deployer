/**
 * Property-based tests for Health Poller
 * Feature: startup-health-check
 * Property 3: Exponential Backoff Correctness
 * Validates: Requirements 2.3, 4.3
 */

const { HealthPoller, DEFAULT_CONFIG } = require('../health-poller');

// ============================================
// Property 3: Exponential Backoff Correctness
// Validates: Requirements 2.3, 4.3
// ============================================

describe('Property 3: Exponential Backoff Correctness', () => {
  describe('calculateDelay', () => {
    test('delay at attempt 0 equals initialDelayMs', () => {
      const poller = new HealthPoller({ initialDelayMs: 100 });
      expect(poller.calculateDelay(0)).toBe(100);
    });

    test('delay increases exponentially with each attempt', () => {
      const poller = new HealthPoller({
        initialDelayMs: 100,
        backoffMultiplier: 1.5,
        maxDelayMs: 10000,
      });

      const delays = [];
      for (let i = 0; i < 10; i++) {
        delays.push(poller.calculateDelay(i));
      }

      // Each delay should be greater than or equal to the previous
      for (let i = 1; i < delays.length; i++) {
        expect(delays[i]).toBeGreaterThanOrEqual(delays[i - 1]);
      }
    });

    test('delay follows formula: initialDelay * multiplier^attempt', () => {
      const initialDelayMs = 100;
      const backoffMultiplier = 1.5;
      const maxDelayMs = 10000;

      const poller = new HealthPoller({
        initialDelayMs,
        backoffMultiplier,
        maxDelayMs,
      });

      // Test first 5 attempts
      for (let attempt = 0; attempt < 5; attempt++) {
        const expected = Math.min(
          Math.round(initialDelayMs * Math.pow(backoffMultiplier, attempt)),
          maxDelayMs
        );
        expect(poller.calculateDelay(attempt)).toBe(expected);
      }
    });

    test('delay is capped at maxDelayMs', () => {
      const poller = new HealthPoller({
        initialDelayMs: 100,
        backoffMultiplier: 2,
        maxDelayMs: 500,
      });

      // After enough attempts, delay should be capped
      for (let i = 10; i < 20; i++) {
        expect(poller.calculateDelay(i)).toBeLessThanOrEqual(500);
      }
    });

    test('delay never exceeds maxDelayMs for any attempt', () => {
      const poller = new HealthPoller({
        initialDelayMs: 100,
        backoffMultiplier: 1.5,
        maxDelayMs: 2000,
      });

      // Test 100 attempts
      for (let i = 0; i < 100; i++) {
        expect(poller.calculateDelay(i)).toBeLessThanOrEqual(2000);
      }
    });

    test('delay is always positive', () => {
      const poller = new HealthPoller({
        initialDelayMs: 100,
        backoffMultiplier: 1.5,
        maxDelayMs: 2000,
      });

      for (let i = 0; i < 100; i++) {
        expect(poller.calculateDelay(i)).toBeGreaterThan(0);
      }
    });

    // Property-based test: For any valid configuration
    test.each([
      { initialDelayMs: 50, backoffMultiplier: 1.2, maxDelayMs: 1000 },
      { initialDelayMs: 100, backoffMultiplier: 1.5, maxDelayMs: 2000 },
      { initialDelayMs: 200, backoffMultiplier: 2.0, maxDelayMs: 5000 },
      { initialDelayMs: 10, backoffMultiplier: 1.1, maxDelayMs: 500 },
    ])('delay properties hold for config %j', (config) => {
      const poller = new HealthPoller(config);

      let prevDelay = 0;
      for (let i = 0; i < 50; i++) {
        const delay = poller.calculateDelay(i);

        // Delay is positive
        expect(delay).toBeGreaterThan(0);

        // Delay is capped
        expect(delay).toBeLessThanOrEqual(config.maxDelayMs);

        // Delay is non-decreasing
        expect(delay).toBeGreaterThanOrEqual(prevDelay);

        prevDelay = delay;
      }
    });
  });
});

describe('HealthPoller Configuration', () => {
  test('uses default configuration when no options provided', () => {
    const poller = new HealthPoller();
    const config = poller.getConfig();

    expect(config.baseUrl).toBe(DEFAULT_CONFIG.baseUrl);
    expect(config.maxAttempts).toBe(DEFAULT_CONFIG.maxAttempts);
    expect(config.initialDelayMs).toBe(DEFAULT_CONFIG.initialDelayMs);
    expect(config.maxDelayMs).toBe(DEFAULT_CONFIG.maxDelayMs);
  });

  test('overrides default configuration with provided options', () => {
    const poller = new HealthPoller({
      baseUrl: 'http://localhost:9090',
      maxAttempts: 100,
    });
    const config = poller.getConfig();

    expect(config.baseUrl).toBe('http://localhost:9090');
    expect(config.maxAttempts).toBe(100);
    // Other defaults should remain
    expect(config.initialDelayMs).toBe(DEFAULT_CONFIG.initialDelayMs);
  });
});

describe('HealthPoller Callback', () => {
  test('onAttempt callback is called with correct parameters', async () => {
    const attempts = [];
    const poller = new HealthPoller({
      maxAttempts: 3,
      initialDelayMs: 10,
      maxDelayMs: 50,
      onAttempt: (info) => attempts.push(info),
    });

    // Mock checkHealth to always return not ready
    poller.checkHealth = jest.fn().mockResolvedValue({ ready: false, error: 'test' });

    await poller.waitForReady();

    expect(attempts.length).toBe(3);
    expect(attempts[0].attempt).toBe(1);
    expect(attempts[1].attempt).toBe(2);
    expect(attempts[2].attempt).toBe(3);

    // Each attempt should have required fields
    attempts.forEach((info) => {
      expect(info).toHaveProperty('attempt');
      expect(info).toHaveProperty('maxAttempts');
      expect(info).toHaveProperty('delay');
      expect(info).toHaveProperty('elapsedMs');
    });
  });
});

describe('HealthPoller waitForReady', () => {
  test('returns ready=true when backend is ready', async () => {
    const poller = new HealthPoller({ maxAttempts: 5 });
    
    poller.checkHealth = jest.fn().mockResolvedValue({
      ready: true,
      response: { ready: true, phase: 'ready' },
    });

    const result = await poller.waitForReady();

    expect(result.ready).toBe(true);
    expect(result.attempts).toBe(1);
    expect(result.response).toEqual({ ready: true, phase: 'ready' });
  });

  test('returns ready=false after max attempts', async () => {
    const poller = new HealthPoller({
      maxAttempts: 3,
      initialDelayMs: 10,
      maxDelayMs: 20,
    });
    
    poller.checkHealth = jest.fn().mockResolvedValue({
      ready: false,
      error: 'Not ready',
    });

    const result = await poller.waitForReady();

    expect(result.ready).toBe(false);
    expect(result.attempts).toBe(3);
    expect(result.error).toBeDefined();
  });

  test('succeeds after multiple attempts', async () => {
    const poller = new HealthPoller({
      maxAttempts: 10,
      initialDelayMs: 10,
      maxDelayMs: 50,
    });
    
    let callCount = 0;
    poller.checkHealth = jest.fn().mockImplementation(() => {
      callCount++;
      if (callCount >= 3) {
        return Promise.resolve({
          ready: true,
          response: { ready: true, phase: 'ready' },
        });
      }
      return Promise.resolve({
        ready: false,
        response: { ready: false, phase: 'initializing' },
      });
    });

    const result = await poller.waitForReady();

    expect(result.ready).toBe(true);
    expect(result.attempts).toBe(3);
  });

  test('tracks total time correctly', async () => {
    const poller = new HealthPoller({
      maxAttempts: 2,
      initialDelayMs: 50,
      maxDelayMs: 100,
    });
    
    poller.checkHealth = jest.fn().mockResolvedValue({
      ready: false,
      error: 'Not ready',
    });

    const startTime = Date.now();
    const result = await poller.waitForReady();
    const elapsed = Date.now() - startTime;

    expect(result.totalTimeMs).toBeGreaterThan(0);
    expect(result.totalTimeMs).toBeLessThanOrEqual(elapsed + 100); // Allow some margin
  });
});

describe('HealthPoller sleep', () => {
  test('sleep waits for specified duration', async () => {
    const poller = new HealthPoller();
    const sleepTime = 100;

    const startTime = Date.now();
    await poller.sleep(sleepTime);
    const elapsed = Date.now() - startTime;

    // Allow 20ms margin for timing variations
    expect(elapsed).toBeGreaterThanOrEqual(sleepTime - 20);
    expect(elapsed).toBeLessThan(sleepTime + 50);
  });
});
