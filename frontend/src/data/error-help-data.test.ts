/**
 * Property-Based Tests for Error Help Data
 * Feature: iam-permission-documentation
 */
import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import {
  ERROR_HELP_DATA,
  getErrorHelp,
  getAllErrorTypes,
  matchErrorType,
  ErrorType
} from './error-help-data';

describe('Error Help Data - Property Tests', () => {
  /**
   * Property 6: Error Type Contextual Help Coverage
   * For any error type that can occur during permission verification,
   * there SHALL exist a corresponding contextual help entry with a
   * non-empty description and at least one remediation step.
   * 
   * Validates: Requirements 7.5
   */
  describe('Property 6: Error Type Contextual Help Coverage', () => {
    it('all error types have contextual help entries', () => {
      const allTypes = getAllErrorTypes();
      
      for (const errorType of allTypes) {
        const help = getErrorHelp(errorType);
        expect(help).toBeDefined();
        expect(help.type).toBe(errorType);
      }
    });

    it('all error help entries have non-empty description', () => {
      const allTypes = getAllErrorTypes();
      
      for (const errorType of allTypes) {
        const help = getErrorHelp(errorType);
        expect(help.description).toBeDefined();
        expect(typeof help.description).toBe('string');
        expect(help.description.length).toBeGreaterThan(0);
      }
    });

    it('all error help entries have at least one remediation step', () => {
      const allTypes = getAllErrorTypes();
      
      for (const errorType of allTypes) {
        const help = getErrorHelp(errorType);
        expect(help.remediation).toBeDefined();
        expect(Array.isArray(help.remediation)).toBe(true);
        expect(help.remediation.length).toBeGreaterThan(0);
      }
    });

    it('all remediation steps have valid structure', () => {
      const allTypes = getAllErrorTypes();
      
      for (const errorType of allTypes) {
        const help = getErrorHelp(errorType);
        
        for (const step of help.remediation) {
          // Step number should be positive
          expect(step.step).toBeGreaterThan(0);
          
          // Instruction should be non-empty
          expect(step.instruction).toBeDefined();
          expect(typeof step.instruction).toBe('string');
          expect(step.instruction.length).toBeGreaterThan(0);
          
          // If command exists, it should be non-empty
          if (step.command !== undefined) {
            expect(typeof step.command).toBe('string');
            expect(step.command.length).toBeGreaterThan(0);
          }
          
          // If link exists, it should be a valid URL
          if (step.link !== undefined) {
            expect(typeof step.link).toBe('string');
            expect(step.link).toMatch(/^https?:\/\//);
          }
        }
      }
    });

    it('remediation steps are numbered sequentially', () => {
      const allTypes = getAllErrorTypes();
      
      for (const errorType of allTypes) {
        const help = getErrorHelp(errorType);
        
        for (let i = 0; i < help.remediation.length; i++) {
          expect(help.remediation[i].step).toBe(i + 1);
        }
      }
    });

    it('all error help entries have non-empty title', () => {
      const allTypes = getAllErrorTypes();
      
      for (const errorType of allTypes) {
        const help = getErrorHelp(errorType);
        expect(help.title).toBeDefined();
        expect(typeof help.title).toBe('string');
        expect(help.title.length).toBeGreaterThan(0);
      }
    });
  });

  describe('Error Type Matching', () => {
    it('matches access denied errors correctly', () => {
      const testMessages = [
        'Access Denied',
        'User is not authorized to perform this action',
        'access denied for resource'
      ];
      
      for (const msg of testMessages) {
        expect(matchErrorType(msg)).toBe('AccessDenied');
      }
    });

    it('matches expired credentials correctly', () => {
      const testMessages = [
        'Token has expired',
        'Credentials expired',
        'Session expired'
      ];
      
      for (const msg of testMessages) {
        expect(matchErrorType(msg)).toBe('ExpiredCredentials');
      }
    });

    it('matches network errors correctly', () => {
      const testMessages = [
        'Network error occurred',
        'Connection timeout',
        'Unable to connect'
      ];
      
      for (const msg of testMessages) {
        expect(matchErrorType(msg)).toBe('NetworkError');
      }
    });

    it('returns null for unrecognized errors', () => {
      const result = matchErrorType('Some random error message');
      expect(result).toBeNull();
    });
  });

  describe('Error Help Data Integrity', () => {
    it('ERROR_HELP_DATA contains all expected error types', () => {
      const expectedTypes: ErrorType[] = [
        'AccessDenied',
        'InvalidRoleArn',
        'ExpiredCredentials',
        'InsufficientPermissions',
        'CrossAccountTrustFailure',
        'NetworkError',
        'RateLimitExceeded',
        'InvalidExternalId',
        'MalformedPolicy',
        'ServiceUnavailable'
      ];
      
      for (const type of expectedTypes) {
        expect(ERROR_HELP_DATA[type]).toBeDefined();
      }
    });

    it('getAllErrorTypes returns all error types', () => {
      const types = getAllErrorTypes();
      expect(types.length).toBe(Object.keys(ERROR_HELP_DATA).length);
      
      for (const type of types) {
        expect(ERROR_HELP_DATA[type]).toBeDefined();
      }
    });

    it('getErrorHelp returns correct help for each type', () => {
      fc.assert(
        fc.property(
          fc.constantFrom(...getAllErrorTypes()),
          (errorType) => {
            const help = getErrorHelp(errorType);
            expect(help.type).toBe(errorType);
            expect(help.description.length).toBeGreaterThan(0);
            expect(help.remediation.length).toBeGreaterThan(0);
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  describe('Property-Based Error Matching', () => {
    it('matched error types always have help available', () => {
      const errorMessages = [
        'Access Denied',
        'Invalid ARN format',
        'Token has expired',
        'Insufficient permissions',
        'Cross-account trust failure',
        'Network connection error',
        'Rate limit exceeded',
        'Invalid external ID',
        'Malformed policy syntax',
        'Service unavailable'
      ];
      
      fc.assert(
        fc.property(
          fc.constantFrom(...errorMessages),
          (message) => {
            const errorType = matchErrorType(message);
            if (errorType !== null) {
              const help = getErrorHelp(errorType);
              expect(help).toBeDefined();
              expect(help.remediation.length).toBeGreaterThan(0);
            }
          }
        ),
        { numRuns: 100 }
      );
    });
  });
});
