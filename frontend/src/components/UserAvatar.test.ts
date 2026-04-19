/**
 * UserAvatar Property Tests
 * 
 * Feature: user-menu
 * Property 1: Initials Extraction
 * Validates: Requirements 1.1
 */
import { describe, it, expect } from 'vitest';
import fc from 'fast-check';
import { getInitials } from './UserAvatar';

describe('UserAvatar Properties', () => {
  /**
   * Property 1: Initials Extraction
   * For any non-empty username string, getInitials returns 1-2 uppercase characters
   */
  it('getInitials always returns 1-2 uppercase characters for non-empty strings', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 100 }),
        (username) => {
          const initials = getInitials(username);
          
          // Must return 1-2 characters
          const validLength = initials.length >= 1 && initials.length <= 2;
          
          // Must be uppercase
          const isUppercase = initials === initials.toUpperCase();
          
          // Must only contain letters (or be 'U' for fallback)
          const validChars = /^[A-Z]+$/.test(initials);
          
          return validLength && isUppercase && validChars;
        }
      ),
      { numRuns: 100 }
    );
  });

  /**
   * Property: Empty/whitespace strings return fallback 'U'
   */
  it('getInitials returns "U" for empty or whitespace-only strings', () => {
    fc.assert(
      fc.property(
        fc.stringOf(fc.constantFrom(' ', '\t', '\n', '\r')),
        (whitespace) => {
          const initials = getInitials(whitespace);
          return initials === 'U';
        }
      ),
      { numRuns: 50 }
    );
  });

  /**
   * Property: Initials are deterministic
   */
  it('getInitials is deterministic - same input always produces same output', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 50 }),
        (username) => {
          const result1 = getInitials(username);
          const result2 = getInitials(username);
          return result1 === result2;
        }
      ),
      { numRuns: 100 }
    );
  });
});

describe('UserAvatar Unit Tests', () => {
  it('extracts single initial from single character', () => {
    expect(getInitials('A')).toBe('A');
    expect(getInitials('z')).toBe('Z');
  });

  it('extracts two initials from single word', () => {
    expect(getInitials('Admin')).toBe('AD');
    expect(getInitials('john')).toBe('JO');
  });

  it('extracts initials from two words', () => {
    expect(getInitials('John Doe')).toBe('JD');
    expect(getInitials('jane smith')).toBe('JS');
  });

  it('handles underscores as separators', () => {
    expect(getInitials('john_doe')).toBe('JD');
  });

  it('handles dots as separators', () => {
    expect(getInitials('john.doe')).toBe('JD');
  });

  it('handles hyphens as separators', () => {
    expect(getInitials('john-doe')).toBe('JD');
  });

  it('returns U for empty string', () => {
    expect(getInitials('')).toBe('U');
  });

  it('returns U for null/undefined-like input', () => {
    expect(getInitials('')).toBe('U');
    expect(getInitials('   ')).toBe('U');
  });

  it('handles multiple spaces between words', () => {
    expect(getInitials('John    Doe')).toBe('JD');
  });
});
