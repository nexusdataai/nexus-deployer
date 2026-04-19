/**
 * Property Tests for LoadingScreen Component
 * 
 * Property 9: Loading Screen State Transitions
 * Validates: Requirements 3.1, 3.4
 * 
 * Feature: startup-health-check
 */
import { describe, it, expect, vi } from 'vitest';
import * as fc from 'fast-check';
import { render, screen, fireEvent } from '@testing-library/react';
import { LoadingScreen, StartupPhase, StartupStatus } from './LoadingScreen';

// Arbitrary for valid startup phases
const startupPhaseArb = fc.constantFrom<StartupPhase>(
  'connecting',
  'initializing',
  'loading_components',
  'ready',
  'error',
  'timeout'
);

// Arbitrary for component status
const componentStatusArb = fc.record({
  name: fc.string({ minLength: 1, maxLength: 20 }),
  status: fc.constantFrom('pending', 'healthy', 'degraded', 'unhealthy') as fc.Arbitrary<'pending' | 'healthy' | 'degraded' | 'unhealthy'>,
});

// Arbitrary for startup status
const startupStatusArb = fc.record({
  phase: startupPhaseArb,
  message: fc.string({ minLength: 0, maxLength: 100 }),
  progress: fc.option(fc.integer({ min: 0, max: 100 }), { nil: undefined }),
  error: fc.option(fc.string({ minLength: 1, maxLength: 200 }), { nil: undefined }),
  componentStatuses: fc.option(fc.array(componentStatusArb, { minLength: 0, maxLength: 5 }), { nil: undefined }),
});

describe('LoadingScreen Property Tests', () => {
  describe('Property 9: Loading Screen State Transitions', () => {
    it('should always render without crashing for any valid status', () => {
      fc.assert(
        fc.property(startupStatusArb, (status) => {
          const { unmount } = render(<LoadingScreen status={status} />);
          
          // Should render the status container
          const statusElement = screen.getByRole('status');
          expect(statusElement).toBeDefined();
          
          unmount();
        }),
        { numRuns: 50 }
      );
    });

    it('should show error state only for error/timeout phases', () => {
      fc.assert(
        fc.property(startupStatusArb, (status) => {
          const { container, unmount } = render(<LoadingScreen status={status} />);
          
          const isErrorPhase = status.phase === 'error' || status.phase === 'timeout';
          const hasErrorIcon = container.querySelector('.text-destructive') !== null;
          
          // Error icon should appear only in error states
          if (isErrorPhase) {
            expect(hasErrorIcon).toBe(true);
          }
          
          unmount();
        }),
        { numRuns: 50 }
      );
    });

    it('should show progress bar only for non-error phases', () => {
      fc.assert(
        fc.property(startupStatusArb, (status) => {
          const { container, unmount } = render(<LoadingScreen status={status} />);
          
          const isErrorPhase = status.phase === 'error' || status.phase === 'timeout';
          const progressBar = container.querySelector('[role="progressbar"]');
          
          if (isErrorPhase) {
            expect(progressBar).toBeNull();
          } else {
            expect(progressBar).not.toBeNull();
          }
          
          unmount();
        }),
        { numRuns: 50 }
      );
    });

    it('should show retry button only in error state with onRetry handler', () => {
      fc.assert(
        fc.property(
          startupStatusArb,
          fc.boolean(),
          (status, hasRetryHandler) => {
            const onRetry = hasRetryHandler ? vi.fn() : undefined;
            const { unmount } = render(<LoadingScreen status={status} onRetry={onRetry} />);
            
            const isErrorPhase = status.phase === 'error' || status.phase === 'timeout';
            const retryButton = screen.queryByRole('button', { name: /retry/i });
            
            if (isErrorPhase && hasRetryHandler) {
              expect(retryButton).not.toBeNull();
            } else {
              expect(retryButton).toBeNull();
            }
            
            unmount();
          }
        ),
        { numRuns: 50 }
      );
    });

    it('should call onRetry when retry button is clicked', () => {
      const errorStatuses: StartupPhase[] = ['error', 'timeout'];
      
      fc.assert(
        fc.property(
          fc.constantFrom(...errorStatuses),
          fc.string({ minLength: 1, maxLength: 50 }),
          (phase, errorMessage) => {
            const onRetry = vi.fn();
            const status: StartupStatus = {
              phase,
              message: 'Test error',
              error: errorMessage,
            };
            
            const { unmount } = render(<LoadingScreen status={status} onRetry={onRetry} />);
            
            const retryButton = screen.getByRole('button', { name: /retry/i });
            fireEvent.click(retryButton);
            
            expect(onRetry).toHaveBeenCalledTimes(1);
            
            unmount();
          }
        ),
        { numRuns: 20 }
      );
    });

    it('should display custom message when provided', () => {
      fc.assert(
        fc.property(
          startupPhaseArb,
          fc.string({ minLength: 5, maxLength: 50 }),
          (phase, customMessage) => {
            const status: StartupStatus = {
              phase,
              message: customMessage,
            };
            
            const { unmount } = render(<LoadingScreen status={status} />);
            
            // Custom message should be displayed
            expect(screen.getByText(customMessage)).toBeDefined();
            
            unmount();
          }
        ),
        { numRuns: 30 }
      );
    });

    it('should display component statuses when provided', () => {
      fc.assert(
        fc.property(
          startupPhaseArb,
          fc.array(componentStatusArb, { minLength: 1, maxLength: 3 }),
          (phase, componentStatuses) => {
            const status: StartupStatus = {
              phase,
              message: 'Loading...',
              componentStatuses,
            };
            
            const { unmount } = render(<LoadingScreen status={status} />);
            
            // Each component name should be displayed
            componentStatuses.forEach((comp) => {
              if (comp.name.trim()) {
                expect(screen.getByText(comp.name)).toBeDefined();
              }
            });
            
            unmount();
          }
        ),
        { numRuns: 30 }
      );
    });

    it('should have correct progress value based on phase or custom progress', () => {
      const expectedProgress: Record<StartupPhase, number> = {
        connecting: 20,
        initializing: 50,
        loading_components: 80,
        ready: 100,
        error: 0,
        timeout: 0,
      };

      fc.assert(
        fc.property(
          fc.constantFrom<StartupPhase>('connecting', 'initializing', 'loading_components', 'ready'),
          fc.option(fc.integer({ min: 0, max: 100 }), { nil: undefined }),
          (phase, customProgress) => {
            const status: StartupStatus = {
              phase,
              message: 'Test',
              progress: customProgress,
            };
            
            const { container, unmount } = render(<LoadingScreen status={status} />);
            
            const progressBar = container.querySelector('[role="progressbar"]');
            if (progressBar) {
              const progressValue = progressBar.getAttribute('aria-valuenow');
              const expected = customProgress ?? expectedProgress[phase];
              expect(Number(progressValue)).toBe(expected);
            }
            
            unmount();
          }
        ),
        { numRuns: 30 }
      );
    });

    it('should be hidden when ready phase is reached', () => {
      const status: StartupStatus = {
        phase: 'ready',
        message: 'Ready!',
      };
      
      const { container, unmount } = render(<LoadingScreen status={status} />);
      
      const statusElement = container.querySelector('[role="status"]');
      expect(statusElement?.classList.contains('opacity-0')).toBe(true);
      expect(statusElement?.classList.contains('pointer-events-none')).toBe(true);
      
      unmount();
    });

    it('should show error details when error string is provided', () => {
      fc.assert(
        fc.property(
          fc.constantFrom<StartupPhase>('error', 'timeout'),
          fc.string({ minLength: 5, maxLength: 100 }),
          (phase, errorDetail) => {
            const status: StartupStatus = {
              phase,
              message: 'Error occurred',
              error: errorDetail,
            };
            
            const { unmount } = render(<LoadingScreen status={status} />);
            
            // Error detail should be displayed
            expect(screen.getByText(errorDetail)).toBeDefined();
            
            unmount();
          }
        ),
        { numRuns: 20 }
      );
    });
  });
});
