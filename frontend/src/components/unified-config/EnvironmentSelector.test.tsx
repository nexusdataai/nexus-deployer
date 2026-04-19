/**
 * Property-based tests for EnvironmentSelector component
 * Feature: unified-environment-config, Property 2: Environment Selection Visual Feedback
 * Validates: Requirements 2.2
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import * as fc from 'fast-check';
import EnvironmentSelector from './EnvironmentSelector';
import { EnvironmentType } from './EnvironmentBox';

describe('EnvironmentSelector - Property Tests', () => {
  /**
   * Property 2: Environment Selection Visual Feedback
   * For any environment selection, the selected EnvironmentBox SHALL have distinct visual styling
   * (border/background) compared to unselected boxes, and exactly one environment SHALL be selected at any time.
   */
  it('should visually highlight only the selected environment box', () => {
    fc.assert(
      fc.property(
        fc.constantFrom<EnvironmentType>('dev', 'test', 'stage', 'prod'),
        (selectedEnv) => {
          const { unmount } = render(
            <EnvironmentSelector
              selectedEnvironment={selectedEnv}
              onEnvironmentChange={() => {}}
            />
          );

          // Get the selected box
          const selectedBox = screen.getByTestId(`env-box-${selectedEnv}`);
          
          // Verify selected box has the selection styling
          expect(selectedBox.className).toContain('ring-2');
          expect(selectedBox.className).toContain('ring-blue-600');
          expect(selectedBox.className).toContain('border-blue-600');
          expect(selectedBox.className).toContain('bg-blue-50');

          // Verify all other boxes do NOT have selection styling
          const allEnvTypes: EnvironmentType[] = ['dev', 'test', 'stage', 'prod'];
          const unselectedEnvs = allEnvTypes.filter(env => env !== selectedEnv);
          
          unselectedEnvs.forEach(envType => {
            const unselectedBox = screen.getByTestId(`env-box-${envType}`);
            expect(unselectedBox.className).not.toContain('ring-2');
            expect(unselectedBox.className).not.toContain('ring-blue-600');
          });

          unmount();
        }
      ),
      { numRuns: 100 }
    );
  });

  it('should render exactly 4 environment boxes', () => {
    const { container } = render(
      <EnvironmentSelector
        selectedEnvironment="prod"
        onEnvironmentChange={() => {}}
      />
    );

    const envBoxes = container.querySelectorAll('[data-testid^="env-box-"]');
    expect(envBoxes.length).toBe(4);
  });

  it('should call onEnvironmentChange when an environment is clicked', () => {
    fc.assert(
      fc.property(
        fc.constantFrom<EnvironmentType>('dev', 'test', 'stage', 'prod'),
        fc.constantFrom<EnvironmentType>('dev', 'test', 'stage', 'prod'),
        (currentEnv, clickedEnv) => {
          const mockOnChange = vi.fn();
          const { unmount } = render(
            <EnvironmentSelector
              selectedEnvironment={currentEnv}
              onEnvironmentChange={mockOnChange}
            />
          );

          const boxToClick = screen.getByTestId(`env-box-${clickedEnv}`);
          boxToClick.click();

          expect(mockOnChange).toHaveBeenCalledWith(clickedEnv);

          unmount();
        }
      ),
      { numRuns: 100 }
    );
  });
});
