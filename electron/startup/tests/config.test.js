/**
 * Property Tests for Startup Configuration
 * 
 * Property 10: Configuration Defaults
 * Validates: Requirements 7.5, 7.6
 * 
 * Feature: startup-health-check
 */

const { describe, it, expect, beforeEach, afterEach } = require('@jest/globals');
const fc = require('fast-check');
const path = require('path');
const fs = require('fs');
const os = require('os');

// Mock electron app
jest.mock('electron', () => ({
  app: {
    getPath: jest.fn(() => os.tmpdir()),
  },
}));

const { StartupConfig, getDefaults, DEFAULT_CONFIG } = require('../config');

describe('StartupConfig Property Tests', () => {
  let tempDir;
  let configPath;

  beforeEach(() => {
    tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'startup-config-test-'));
    configPath = path.join(tempDir, 'test-config.json');
  });

  afterEach(() => {
    // Clean up temp directory
    if (fs.existsSync(tempDir)) {
      fs.rmSync(tempDir, { recursive: true, force: true });
    }
    // Clear environment variables
    Object.keys(process.env)
      .filter(key => key.startsWith('STARTUP_'))
      .forEach(key => delete process.env[key]);
  });

  describe('Property 10: Configuration Defaults', () => {
    it('should always return valid defaults for all known keys', () => {
      const defaults = getDefaults();
      
      // All default keys should be defined
      expect(defaults.healthCheckUrl).toBeDefined();
      expect(defaults.healthCheckTimeoutMs).toBeDefined();
      expect(defaults.healthCheckIntervalMs).toBeDefined();
      expect(defaults.backendPort).toBeDefined();
      expect(defaults.maxRestartAttempts).toBeDefined();
    });

    it('should have sensible default values', () => {
      const defaults = getDefaults();
      
      // Timeouts should be positive
      expect(defaults.healthCheckTimeoutMs).toBeGreaterThan(0);
      expect(defaults.healthCheckIntervalMs).toBeGreaterThan(0);
      expect(defaults.backendStartTimeoutMs).toBeGreaterThan(0);
      
      // Port should be valid
      expect(defaults.backendPort).toBeGreaterThanOrEqual(1);
      expect(defaults.backendPort).toBeLessThanOrEqual(65535);
      
      // Multiplier should be >= 1
      expect(defaults.backoffMultiplier).toBeGreaterThanOrEqual(1);
    });

    it('should return independent copies of defaults', () => {
      const defaults1 = getDefaults();
      const defaults2 = getDefaults();
      
      // Modifying one should not affect the other
      defaults1.healthCheckTimeoutMs = 999999;
      expect(defaults2.healthCheckTimeoutMs).toBe(DEFAULT_CONFIG.healthCheckTimeoutMs);
    });

    it('should load defaults when no config file or env vars exist', () => {
      const config = new StartupConfig({ configPath });
      config.load();
      
      const all = config.getAll();
      
      // Should match defaults
      for (const [key, value] of Object.entries(DEFAULT_CONFIG)) {
        expect(all[key]).toBe(value);
      }
    });

    it('should override defaults with file config', () => {
      fc.assert(
        fc.property(
          fc.integer({ min: 1000, max: 120000 }),
          fc.integer({ min: 100, max: 5000 }),
          (timeout, interval) => {
            // Write config file
            const fileConfig = {
              healthCheckTimeoutMs: timeout,
              healthCheckIntervalMs: interval,
            };
            fs.writeFileSync(configPath, JSON.stringify(fileConfig));
            
            const config = new StartupConfig({ configPath });
            config.load();
            
            expect(config.get('healthCheckTimeoutMs')).toBe(timeout);
            expect(config.get('healthCheckIntervalMs')).toBe(interval);
            // Other values should still be defaults
            expect(config.get('backendPort')).toBe(DEFAULT_CONFIG.backendPort);
          }
        ),
        { numRuns: 20 }
      );
    });

    it('should override file config with environment variables', () => {
      fc.assert(
        fc.property(
          fc.integer({ min: 1000, max: 120000 }),
          fc.integer({ min: 1000, max: 120000 }),
          (fileTimeout, envTimeout) => {
            // Write config file
            fs.writeFileSync(configPath, JSON.stringify({
              healthCheckTimeoutMs: fileTimeout,
            }));
            
            // Set environment variable
            process.env.STARTUP_HEALTH_CHECK_TIMEOUT_MS = String(envTimeout);
            
            const config = new StartupConfig({ configPath });
            config.load();
            
            // Environment should win
            expect(config.get('healthCheckTimeoutMs')).toBe(envTimeout);
            
            // Clean up
            delete process.env.STARTUP_HEALTH_CHECK_TIMEOUT_MS;
          }
        ),
        { numRuns: 20 }
      );
    });

    it('should parse boolean environment variables correctly', () => {
      fc.assert(
        fc.property(
          fc.constantFrom('true', 'false', '1', '0', 'TRUE', 'FALSE'),
          (boolStr) => {
            process.env.STARTUP_ENABLE_LOGGING = boolStr;
            
            const config = new StartupConfig({ configPath });
            config.load();
            
            const expected = boolStr.toLowerCase() === 'true' || boolStr === '1';
            expect(config.get('enableStartupLogging')).toBe(expected);
            
            delete process.env.STARTUP_ENABLE_LOGGING;
          }
        ),
        { numRuns: 10 }
      );
    });

    it('should parse numeric environment variables correctly', () => {
      fc.assert(
        fc.property(
          fc.integer({ min: 1, max: 65535 }),
          (port) => {
            process.env.STARTUP_BACKEND_PORT = String(port);
            
            const config = new StartupConfig({ configPath });
            config.load();
            
            expect(config.get('backendPort')).toBe(port);
            expect(typeof config.get('backendPort')).toBe('number');
            
            delete process.env.STARTUP_BACKEND_PORT;
          }
        ),
        { numRuns: 20 }
      );
    });

    it('should handle invalid numeric values gracefully', () => {
      fc.assert(
        fc.property(
          fc.constantFrom('abc', 'not-a-number', '', '   '),
          (invalidValue) => {
            process.env.STARTUP_BACKEND_PORT = invalidValue;
            
            const config = new StartupConfig({ configPath });
            config.load();
            
            // Should fall back to default
            expect(config.get('backendPort')).toBe(DEFAULT_CONFIG.backendPort);
            
            delete process.env.STARTUP_BACKEND_PORT;
          }
        ),
        { numRuns: 10 }
      );
    });

    it('should validate configuration correctly', () => {
      fc.assert(
        fc.property(
          fc.integer({ min: -1000, max: 500 }),
          fc.integer({ min: -100, max: 50 }),
          fc.float({ min: 0, max: 0.9 }),
          (timeout, interval, multiplier) => {
            const config = new StartupConfig({ configPath });
            config.load();
            
            // Set invalid values
            config.set('healthCheckTimeoutMs', timeout);
            config.set('healthCheckIntervalMs', interval);
            config.set('backoffMultiplier', multiplier);
            
            const validation = config.validate();
            
            // Should have validation errors for invalid values
            if (timeout < 1000) {
              expect(validation.errors.some(e => e.includes('healthCheckTimeoutMs'))).toBe(true);
            }
            if (interval < 100) {
              expect(validation.errors.some(e => e.includes('healthCheckIntervalMs'))).toBe(true);
            }
            if (multiplier < 1) {
              expect(validation.errors.some(e => e.includes('backoffMultiplier'))).toBe(true);
            }
          }
        ),
        { numRuns: 20 }
      );
    });

    it('should pass validation with valid configuration', () => {
      fc.assert(
        fc.property(
          fc.integer({ min: 1000, max: 120000 }),
          fc.integer({ min: 100, max: 5000 }),
          fc.float({ min: 1, max: 3 }),
          fc.integer({ min: 1, max: 65535 }),
          (timeout, interval, multiplier, port) => {
            const config = new StartupConfig({ configPath });
            config.load();
            
            config.set('healthCheckTimeoutMs', timeout);
            config.set('healthCheckIntervalMs', interval);
            config.set('backoffMultiplier', multiplier);
            config.set('backendPort', port);
            
            const validation = config.validate();
            expect(validation.isValid).toBe(true);
            expect(validation.errors).toHaveLength(0);
          }
        ),
        { numRuns: 20 }
      );
    });

    it('should save and reload configuration correctly', () => {
      fc.assert(
        fc.property(
          fc.integer({ min: 1000, max: 120000 }),
          fc.string({ minLength: 1, maxLength: 50 }),
          (timeout, host) => {
            const config1 = new StartupConfig({ configPath });
            config1.load();
            config1.set('healthCheckTimeoutMs', timeout);
            config1.set('backendHost', host);
            config1.save();
            
            // Load in new instance
            const config2 = new StartupConfig({ configPath });
            config2.load();
            
            expect(config2.get('healthCheckTimeoutMs')).toBe(timeout);
            expect(config2.get('backendHost')).toBe(host);
          }
        ),
        { numRuns: 10 }
      );
    });

    it('should reset to defaults correctly', () => {
      const config = new StartupConfig({ configPath });
      config.load();
      
      // Modify some values
      config.set('healthCheckTimeoutMs', 999999);
      config.set('backendPort', 9999);
      
      // Reset
      config.reset();
      
      // Should be back to defaults
      expect(config.get('healthCheckTimeoutMs')).toBe(DEFAULT_CONFIG.healthCheckTimeoutMs);
      expect(config.get('backendPort')).toBe(DEFAULT_CONFIG.backendPort);
    });

    it('should ignore unknown keys in config file', () => {
      fc.assert(
        fc.property(
          fc.string({ minLength: 1, maxLength: 20 }),
          fc.anything(),
          (unknownKey, unknownValue) => {
            // Ensure key doesn't exist in defaults
            if (unknownKey in DEFAULT_CONFIG) return;
            
            const fileConfig = {
              [unknownKey]: unknownValue,
              healthCheckTimeoutMs: 5000,
            };
            fs.writeFileSync(configPath, JSON.stringify(fileConfig));
            
            const config = new StartupConfig({ configPath });
            config.load();
            
            // Unknown key should not be in config
            expect(config.get(unknownKey)).toBeUndefined();
            // Known key should be loaded
            expect(config.get('healthCheckTimeoutMs')).toBe(5000);
          }
        ),
        { numRuns: 10 }
      );
    });
  });
});
