/**
 * Property-based tests for Startup Orchestrator
 * Feature: startup-health-check
 * Property 6: Timeout Enforcement
 * Property 7: Service Recovery Detection
 * Validates: Requirements 2.4, 7.1, 7.3, 9.1, 9.2
 */

const { StartupOrchestrator, StartupPhase, DEFAULT_CONFIG } = require('../orchestrator');

// ============================================
// Property 6: Timeout Enforcement
// Validates: Requirements 2.4, 7.1, 7.3
// ============================================

describe('Property 6: Timeout Enforcement', () => {
  describe('Configuration', () => {
    test('default timeout is 30 seconds', () => {
      expect(DEFAULT_CONFIG.backendStartupTimeoutMs).toBe(30000);
    });

    test('timeout can be configured', () => {
      const orchestrator = new StartupOrchestrator({
        backendStartupTimeoutMs: 60000,
        isDev: true,
      });
      expect(orchestrator.config.backendStartupTimeoutMs).toBe(60000);
    });

    test('health poll max attempts respects timeout', () => {
      const orchestrator = new StartupOrchestrator({
        healthPollConfig: {
          maxAttempts: 100,
          initialDelayMs: 100,
        },
        isDev: true,
      });
      
      // With 100 attempts at 100ms initial delay, should timeout appropriately
      expect(orchestrator.healthPoller.config.maxAttempts).toBe(100);
    });
  });

  describe('Timeout Behavior', () => {
    test('returns error when backend not ready within timeout', async () => {
      const orchestrator = new StartupOrchestrator({
        isDev: true,
        healthPollConfig: {
          maxAttempts: 3,
          initialDelayMs: 10,
          maxDelayMs: 20,
        },
      });

      // Mock health poller to always return not ready
      orchestrator.healthPoller.checkHealth = jest.fn().mockResolvedValue({
        ready: false,
        error: 'Not ready',
      });

      const result = await orchestrator.start();

      expect(result.success).toBe(false);
      expect(result.error).toContain('not ready');
      expect(orchestrator.phase).toBe(StartupPhase.ERROR);
    });

    test('succeeds when backend becomes ready within timeout', async () => {
      const orchestrator = new StartupOrchestrator({
        isDev: true,
        healthPollConfig: {
          maxAttempts: 10,
          initialDelayMs: 10,
          maxDelayMs: 50,
        },
      });

      let callCount = 0;
      orchestrator.healthPoller.checkHealth = jest.fn().mockImplementation(() => {
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

      const result = await orchestrator.start();

      expect(result.success).toBe(true);
      expect(orchestrator.phase).toBe(StartupPhase.LOADING_FRONTEND);
    });
  });
});

// ============================================
// Property 7: Service Recovery Detection
// Validates: Requirements 9.1, 9.2
// ============================================

describe('Property 7: Service Recovery Detection', () => {
  describe('Crash Detection', () => {
    test('max restart attempts is configurable', () => {
      const orchestrator = new StartupOrchestrator({
        maxRestartAttempts: 5,
        isDev: true,
      });
      expect(orchestrator.config.maxRestartAttempts).toBe(5);
    });

    test('default max restart attempts is 3', () => {
      expect(DEFAULT_CONFIG.maxRestartAttempts).toBe(3);
    });

    test('restart count increments on each crash', async () => {
      const orchestrator = new StartupOrchestrator({
        isDev: true,
        maxRestartAttempts: 3,
        healthPollConfig: {
          maxAttempts: 2,
          initialDelayMs: 10,
          maxDelayMs: 20,
        },
      });

      // Mock to always fail
      orchestrator.healthPoller.checkHealth = jest.fn().mockResolvedValue({
        ready: false,
        error: 'Not ready',
      });

      expect(orchestrator.restartCount).toBe(0);

      await orchestrator.handleBackendCrash();
      expect(orchestrator.restartCount).toBe(1);

      await orchestrator.handleBackendCrash();
      expect(orchestrator.restartCount).toBe(2);
    });

    test('stops restarting after max attempts', async () => {
      const orchestrator = new StartupOrchestrator({
        isDev: true,
        maxRestartAttempts: 2,
        healthPollConfig: {
          maxAttempts: 1,
          initialDelayMs: 10,
        },
      });

      orchestrator.healthPoller.checkHealth = jest.fn().mockResolvedValue({
        ready: false,
        error: 'Not ready',
      });

      // First crash
      await orchestrator.handleBackendCrash();
      expect(orchestrator.restartCount).toBe(1);

      // Second crash
      await orchestrator.handleBackendCrash();
      expect(orchestrator.restartCount).toBe(2);

      // Third crash - should exceed max
      const result = await orchestrator.handleBackendCrash();
      expect(result).toBe(false);
      expect(orchestrator.phase).toBe(StartupPhase.ERROR);
    });

    test('recovery succeeds when backend becomes ready', async () => {
      const orchestrator = new StartupOrchestrator({
        isDev: true,
        maxRestartAttempts: 3,
        healthPollConfig: {
          maxAttempts: 5,
          initialDelayMs: 10,
          maxDelayMs: 20,
        },
      });

      orchestrator.healthPoller.checkHealth = jest.fn().mockResolvedValue({
        ready: true,
        response: { ready: true, phase: 'ready' },
      });

      const result = await orchestrator.handleBackendCrash();

      expect(result).toBe(true);
      expect(orchestrator.phase).toBe(StartupPhase.READY);
    });
  });

  describe('Phase Transitions', () => {
    test('phase changes to RECOVERING during crash handling', async () => {
      const phases = [];
      const orchestrator = new StartupOrchestrator({
        isDev: true,
        maxRestartAttempts: 3,
        healthPollConfig: {
          maxAttempts: 1,
          initialDelayMs: 10,
        },
        onStatusChange: (status) => phases.push(status.phase),
      });

      orchestrator.healthPoller.checkHealth = jest.fn().mockResolvedValue({
        ready: true,
        response: { ready: true },
      });

      await orchestrator.handleBackendCrash();

      expect(phases).toContain(StartupPhase.RECOVERING);
    });

    test('phase changes to READY after successful recovery', async () => {
      const orchestrator = new StartupOrchestrator({
        isDev: true,
        healthPollConfig: {
          maxAttempts: 1,
          initialDelayMs: 10,
        },
      });

      orchestrator.healthPoller.checkHealth = jest.fn().mockResolvedValue({
        ready: true,
        response: { ready: true },
      });

      await orchestrator.handleBackendCrash();

      expect(orchestrator.phase).toBe(StartupPhase.READY);
    });

    test('phase changes to ERROR after failed recovery', async () => {
      const orchestrator = new StartupOrchestrator({
        isDev: true,
        maxRestartAttempts: 1,
        healthPollConfig: {
          maxAttempts: 1,
          initialDelayMs: 10,
        },
      });

      orchestrator.healthPoller.checkHealth = jest.fn().mockResolvedValue({
        ready: false,
        error: 'Failed',
      });

      // First crash uses up the one restart attempt
      await orchestrator.handleBackendCrash();
      
      // Second crash exceeds max
      await orchestrator.handleBackendCrash();

      expect(orchestrator.phase).toBe(StartupPhase.ERROR);
    });
  });
});

describe('StartupOrchestrator Status', () => {
  test('getStatus returns correct structure', () => {
    const orchestrator = new StartupOrchestrator({ isDev: true });
    const status = orchestrator.getStatus();

    expect(status).toHaveProperty('phase');
    expect(status).toHaveProperty('progress');
    expect(status).toHaveProperty('message');
    expect(status).toHaveProperty('isDegraded');
    expect(status).toHaveProperty('degradedFeatures');
    expect(status).toHaveProperty('restartCount');
  });

  test('progress is 0-100', () => {
    const orchestrator = new StartupOrchestrator({ isDev: true });

    Object.values(StartupPhase).forEach((phase) => {
      orchestrator.phase = phase;
      const status = orchestrator.getStatus();
      expect(status.progress).toBeGreaterThanOrEqual(0);
      expect(status.progress).toBeLessThanOrEqual(100);
    });
  });

  test('message is non-empty for all phases', () => {
    const orchestrator = new StartupOrchestrator({ isDev: true });

    Object.values(StartupPhase).forEach((phase) => {
      orchestrator.phase = phase;
      const status = orchestrator.getStatus();
      expect(status.message).toBeTruthy();
    });
  });

  test('isDegraded reflects health response', () => {
    const orchestrator = new StartupOrchestrator({ isDev: true });

    orchestrator.lastHealthResponse = { is_degraded: true, degraded_features: ['test'] };
    expect(orchestrator.getStatus().isDegraded).toBe(true);
    expect(orchestrator.getStatus().degradedFeatures).toContain('test');

    orchestrator.lastHealthResponse = { is_degraded: false, degraded_features: [] };
    expect(orchestrator.getStatus().isDegraded).toBe(false);
  });
});

describe('StartupOrchestrator Lifecycle', () => {
  test('stop resets phase to IDLE', async () => {
    const orchestrator = new StartupOrchestrator({ isDev: true });
    orchestrator.phase = StartupPhase.READY;

    await orchestrator.stop();

    expect(orchestrator.phase).toBe(StartupPhase.IDLE);
  });

  test('onStatusChange is called on phase changes', async () => {
    const statusChanges = [];
    const orchestrator = new StartupOrchestrator({
      isDev: true,
      healthPollConfig: {
        maxAttempts: 1,
        initialDelayMs: 10,
      },
      onStatusChange: (status) => statusChanges.push(status),
    });

    orchestrator.healthPoller.checkHealth = jest.fn().mockResolvedValue({
      ready: true,
      response: { ready: true },
    });

    await orchestrator.start();

    expect(statusChanges.length).toBeGreaterThan(0);
    expect(statusChanges.some(s => s.phase === StartupPhase.WAITING_FOR_BACKEND)).toBe(true);
  });
});
