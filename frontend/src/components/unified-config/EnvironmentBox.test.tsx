/**
 * Property-based tests for EnvironmentBox component
 * Feature: unified-environment-config, Property 1: Environment Box Display Completeness
 * Validates: Requirements 2.3, 2.4, 2.5
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import * as fc from 'fast-check';
import EnvironmentBox, { EnvironmentInfo, EnvironmentType } from './EnvironmentBox';

// Environment data for testing
const ENVIRONMENTS: Record<EnvironmentType, EnvironmentInfo> = {
  dev: {
    id: 'dev',
    name: 'Development',
    description: 'Lower resources, cost-optimized for development and testing',
    features: ['No NAT Gateway', 'Minimal auto-scaling', 'Single AZ deployment', 'Reduced instance sizes'],
    estimatedCost: '$40-80/month',
    badge: 'dev',
  },
  test: {
    id: 'test',
    name: 'Test',
    description: 'Similar to dev, isolated environment for testing',
    features: ['Isolated from dev', 'Minimal auto-scaling', 'Single AZ deployment', 'Test data isolation'],
    estimatedCost: '$40-80/month',
    badge: 'test',
  },
  stage: {
    id: 'stage',
    name: 'Staging',
    description: 'Production-like environment for final testing',
    features: ['Full features enabled', 'Moderate auto-scaling', 'Multi-AZ deployment', 'Production-like configuration'],
    estimatedCost: '$150-300/month',
    badge: 'stage',
  },
  prod: {
    id: 'prod',
    name: 'Production',
    description: 'Full HA, auto-scaling, and backups for production workloads',
    features: ['High availability', 'Full auto-scaling', 'Multi-AZ deployment', 'Enhanced monitoring', 'Automated backups'],
    estimatedCost: '$250-500/month',
    badge: 'prod',
  },
};

describe('EnvironmentBox - Property Tests', () => {
  /**
   * Property 1: Environment Box Display Completeness
   * For any environment type (dev, test, stage, prod), the rendered EnvironmentBox component
   * SHALL contain the environment name, identifier badge, and estimated cost range.
   */
  it('should display name, badge, and cost for all environment types', () => {
    fc.assert(
      fc.property(
        fc.constantFrom<EnvironmentType>('dev', 'test', 'stage', 'prod'),
        (envType) => {
          const env = ENVIRONMENTS[envType];
          const { unmount } = render(
            <EnvironmentBox
              environment={env}
              isSelected={false}
              onClick={() => {}}
            />
          );

          // Verify name is displayed
          const nameElement = screen.getByTestId(`env-name-${envType}`);
          expect(nameElement).toBeInTheDocument();
          expect(nameElement.textContent).toBe(env.name);

          // Verify badge is displayed
          const badgeElement = screen.getByTestId(`env-badge-${envType}`);
          expect(badgeElement).toBeInTheDocument();
          expect(badgeElement.textContent).toBe(env.badge);

          // Verify cost is displayed
          const costElement = screen.getByTestId(`env-cost-${envType}`);
          expect(costElement).toBeInTheDocument();
          expect(costElement.textContent).toBe(env.estimatedCost);

          unmount();
        }
      ),
      { numRuns: 100 }
    );
  });

  it('should render the environment box container with correct data attribute', () => {
    fc.assert(
      fc.property(
        fc.constantFrom<EnvironmentType>('dev', 'test', 'stage', 'prod'),
        (envType) => {
          const env = ENVIRONMENTS[envType];
          const { unmount } = render(
            <EnvironmentBox
              environment={env}
              isSelected={false}
              onClick={() => {}}
            />
          );

          const boxElement = screen.getByTestId(`env-box-${envType}`);
          expect(boxElement).toBeInTheDocument();
          expect(boxElement.getAttribute('data-env')).toBe(envType);

          unmount();
        }
      ),
      { numRuns: 100 }
    );
  });
});
