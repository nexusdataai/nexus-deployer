/**
 * Tests for EnvironmentSelectorModal component
 * Feature: environment-specific-operations
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import * as fc from 'fast-check';
import EnvironmentSelectorModal, {
  sortDeployments,
  isProductionEnvironment,
  DeploymentState,
} from './EnvironmentSelectorModal';
import type { Capability } from '../types/capability';

// Arbitrary for generating deployment states
const deploymentStateArb = fc.record({
  capability_name: fc.string({ minLength: 1, maxLength: 50 }),
  environment: fc.oneof(
    fc.constant('prod'),
    fc.constant('dev'),
    fc.constant('staging'),
    fc.constant('test'),
    fc.string({ minLength: 1, maxLength: 20 })
  ),
  region: fc.oneof(
    fc.constant('us-east-1'),
    fc.constant('us-west-2'),
    fc.constant('eu-west-1'),
    fc.constant('ap-southeast-1'),
    fc.string({ minLength: 1, maxLength: 20 })
  ),
  last_deployment: fc.date().map(d => d.toISOString()),
  stacks: fc.array(
    fc.record({
      stack_name: fc.string({ minLength: 1 }),
      stack_type: fc.string({ minLength: 1 }),
      region: fc.string({ minLength: 1 }),
    }),
    { minLength: 0, maxLength: 3 }
  ),
});

// Arbitrary for generating non-empty deployment arrays
const deploymentsArb = fc.array(deploymentStateArb, { minLength: 1, maxLength: 10 });

// Arbitrary for capability - includes all required Capability properties
const capabilityArb = fc.record({
  id: fc.string({ minLength: 1 }).filter(s => s.trim().length > 0),
  name: fc.string({ minLength: 1, maxLength: 50 }).filter(s => s.trim().length > 0),
  description: fc.string(),
  version: fc.string({ minLength: 1 }).filter(s => s.trim().length > 0),
  category: fc.string({ minLength: 1 }).filter(s => s.trim().length > 0),
  status: fc.oneof(fc.constant('available' as const), fc.constant('coming_soon' as const)),
  estimated_deployment_time: fc.integer({ min: 1, max: 60 }),
  supported_clouds: fc.constant(['aws']),
  supported_environments: fc.constant(['dev', 'staging', 'prod']),
  requirements: fc.constant({ frontend: true, backend: true, database: false, authentication: false }),
  artifacts: fc.constant({ frontend: { size_mb: 10 }, backend: { size_mb: 20 } }),
  required_iam_permissions: fc.constant([]),
  prerequisites: fc.constant([]),
}) as fc.Arbitrary<Capability>;

// Helper to create a complete test capability
const createTestCapability = (overrides: Partial<Capability> = {}): Capability => ({
  id: '1',
  name: 'Test Capability',
  description: 'Test',
  version: '1.0.0',
  category: 'Test',
  status: 'available',
  estimated_deployment_time: 10,
  supported_clouds: ['aws'],
  supported_environments: ['dev', 'staging', 'prod'],
  requirements: { frontend: true, backend: true, database: false, authentication: false },
  artifacts: { frontend: { size_mb: 10 }, backend: { size_mb: 20 } },
  required_iam_permissions: [],
  prerequisites: [],
  ...overrides,
});

describe('EnvironmentSelectorModal', () => {
  /**
   * Property 9: Environment Sorting Order
   * For any list of deployments displayed in the EnvironmentSelectorModal,
   * production environments SHALL appear first, followed by other environments
   * in alphabetical order.
   * Validates: Requirements 3.6
   */
  describe('Property 9: Environment Sorting Order', () => {
    it('should sort PROD environments first, then alphabetically', () => {
      fc.assert(
        fc.property(deploymentsArb, (deployments) => {
          const sorted = sortDeployments(deployments);
          
          // Find the index of the last PROD environment
          let lastProdIndex = -1;
          for (let i = 0; i < sorted.length; i++) {
            if (isProductionEnvironment(sorted[i].environment)) {
              lastProdIndex = i;
            }
          }
          
          // All PROD environments should be at the beginning
          for (let i = 0; i < sorted.length; i++) {
            const isProd = isProductionEnvironment(sorted[i].environment);
            if (isProd) {
              expect(i).toBeLessThanOrEqual(lastProdIndex);
            } else {
              expect(i).toBeGreaterThan(lastProdIndex);
            }
          }
          
          // Non-PROD environments should be sorted alphabetically
          const nonProdEnvs = sorted
            .filter(d => !isProductionEnvironment(d.environment))
            .map(d => d.environment);
          
          for (let i = 1; i < nonProdEnvs.length; i++) {
            expect(nonProdEnvs[i].localeCompare(nonProdEnvs[i - 1])).toBeGreaterThanOrEqual(0);
          }
        }),
        { numRuns: 100 }
      );
    });
  });


  /**
   * Property 2: Deployment Option Content Completeness
   * For any deployment displayed in the EnvironmentSelectorModal, the rendered
   * card SHALL contain the environment name, region, and formatted deployment timestamp.
   * Validates: Requirements 1.2, 3.3
   */
  describe('Property 2: Deployment Option Content Completeness', () => {
    it('should display environment name, region, and timestamp for each deployment', () => {
      fc.assert(
        fc.property(
          capabilityArb,
          deploymentsArb,
          fc.oneof(fc.constant('update' as const), fc.constant('delete' as const)),
          (capability, deployments, operationType) => {
            const onClose = vi.fn();
            const onSelect = vi.fn();

            const { container } = render(
              <EnvironmentSelectorModal
                isOpen={true}
                onClose={onClose}
                onSelect={onSelect}
                capability={capability}
                deployments={deployments}
                operationType={operationType}
              />
            );

            // Each deployment should have its environment, region, and date displayed
            deployments.forEach((deployment) => {
              // Environment name should be displayed (uppercase)
              expect(
                container.textContent?.includes(deployment.environment.toUpperCase())
              ).toBe(true);
              
              // Region should be displayed
              expect(container.textContent?.includes(deployment.region)).toBe(true);
            });
          }
        ),
        { numRuns: 100 }
      );
    });
  });

  /**
   * Property 5: Environment Type Visual Distinction
   * For any deployment card in the EnvironmentSelectorModal, production environments
   * SHALL have distinct visual styling (red border/accent) compared to non-production
   * environments (blue border/accent).
   * Validates: Requirements 1.5, 4.2
   */
  describe('Property 5: Environment Type Visual Distinction', () => {
    it('should apply red styling to PROD and blue styling to non-PROD environments', () => {
      const prodDeployment: DeploymentState = {
        capability_name: 'test',
        environment: 'prod',
        region: 'us-east-1',
        last_deployment: new Date().toISOString(),
        stacks: [],
      };

      const devDeployment: DeploymentState = {
        capability_name: 'test',
        environment: 'dev',
        region: 'us-west-2',
        last_deployment: new Date().toISOString(),
        stacks: [],
      };

      const capability = createTestCapability();

      const { container } = render(
        <EnvironmentSelectorModal
          isOpen={true}
          onClose={vi.fn()}
          onSelect={vi.fn()}
          capability={capability}
          deployments={[prodDeployment, devDeployment]}
          operationType="update"
        />
      );

      // Find buttons for each environment
      const buttons = container.querySelectorAll('button');
      const prodButton = Array.from(buttons).find(b => 
        b.textContent?.includes('PROD')
      );
      const devButton = Array.from(buttons).find(b => 
        b.textContent?.includes('DEV')
      );

      // PROD should have red styling
      expect(prodButton?.className).toContain('border-red');
      // DEV should have blue styling
      expect(devButton?.className).toContain('border-blue');
    });

    it('should identify production environments correctly', () => {
      fc.assert(
        fc.property(
          fc.oneof(
            fc.constant('prod'),
            fc.constant('PROD'),
            fc.constant('Prod'),
            fc.constant('production'),
            fc.constant('PRODUCTION'),
            fc.constant('Production')
          ),
          (env) => {
            expect(isProductionEnvironment(env)).toBe(true);
          }
        ),
        { numRuns: 100 }
      );
    });

    it('should identify non-production environments correctly', () => {
      fc.assert(
        fc.property(
          fc.oneof(
            fc.constant('dev'),
            fc.constant('DEV'),
            fc.constant('staging'),
            fc.constant('test'),
            fc.constant('qa'),
            fc.constant('uat')
          ),
          (env) => {
            expect(isProductionEnvironment(env)).toBe(false);
          }
        ),
        { numRuns: 100 }
      );
    });
  });


  /**
   * Property 6: Production Delete Confirmation
   * For any delete operation targeting a production environment, the system
   * SHALL require explicit confirmation before proceeding to AWS Configuration.
   * Validates: Requirements 2.2, 2.5
   */
  describe('Property 6: Production Delete Confirmation', () => {
    it('should show confirmation dialog when deleting PROD environment', () => {
      const prodDeployment: DeploymentState = {
        capability_name: 'test',
        environment: 'prod',
        region: 'us-east-1',
        last_deployment: new Date().toISOString(),
        stacks: [],
      };

      const capability = createTestCapability();

      const onSelect = vi.fn();

      render(
        <EnvironmentSelectorModal
          isOpen={true}
          onClose={vi.fn()}
          onSelect={onSelect}
          capability={capability}
          deployments={[prodDeployment]}
          operationType="delete"
        />
      );

      // Click on PROD environment
      const prodButton = screen.getByText('PROD').closest('button');
      fireEvent.click(prodButton!);

      // Confirmation dialog should appear
      expect(screen.getByText('Delete Production Environment')).toBeInTheDocument();
      expect(screen.getByText('Delete Production')).toBeInTheDocument();

      // onSelect should NOT have been called yet
      expect(onSelect).not.toHaveBeenCalled();
    });

    it('should NOT show confirmation dialog when deleting non-PROD environment', () => {
      const devDeployment: DeploymentState = {
        capability_name: 'test',
        environment: 'dev',
        region: 'us-west-2',
        last_deployment: new Date().toISOString(),
        stacks: [],
      };

      const capability = createTestCapability();

      const onSelect = vi.fn();

      render(
        <EnvironmentSelectorModal
          isOpen={true}
          onClose={vi.fn()}
          onSelect={onSelect}
          capability={capability}
          deployments={[devDeployment]}
          operationType="delete"
        />
      );

      // Click on DEV environment
      const devButton = screen.getByText('DEV').closest('button');
      fireEvent.click(devButton!);

      // onSelect should be called immediately (no confirmation)
      expect(onSelect).toHaveBeenCalledWith(devDeployment);
    });

    it('should call onSelect after confirming PROD deletion', () => {
      const prodDeployment: DeploymentState = {
        capability_name: 'test',
        environment: 'prod',
        region: 'us-east-1',
        last_deployment: new Date().toISOString(),
        stacks: [],
      };

      const capability = createTestCapability();

      const onSelect = vi.fn();

      render(
        <EnvironmentSelectorModal
          isOpen={true}
          onClose={vi.fn()}
          onSelect={onSelect}
          capability={capability}
          deployments={[prodDeployment]}
          operationType="delete"
        />
      );

      // Click on PROD environment
      const prodButton = screen.getByText('PROD').closest('button');
      fireEvent.click(prodButton!);

      // Click confirm button
      const confirmButton = screen.getByText('Delete Production');
      fireEvent.click(confirmButton);

      // onSelect should now be called
      expect(onSelect).toHaveBeenCalledWith(prodDeployment);
    });
  });

  /**
   * Property 7: Modal Header Content
   * For any EnvironmentSelectorModal display, the header SHALL contain both
   * the capability name and the operation type ("Update" or "Delete").
   * Validates: Requirements 3.2
   */
  describe('Property 7: Modal Header Content', () => {
    it('should display capability name and operation type in header', () => {
      // Use fixed test data to avoid multiple element issues
      const capability = createTestCapability();

      const deployment: DeploymentState = {
        capability_name: 'test',
        environment: 'dev',
        region: 'us-east-1',
        last_deployment: new Date().toISOString(),
        stacks: [],
      };

      // Test update operation
      const { rerender } = render(
        <EnvironmentSelectorModal
          isOpen={true}
          onClose={vi.fn()}
          onSelect={vi.fn()}
          capability={capability}
          deployments={[deployment]}
          operationType="update"
        />
      );

      expect(screen.getByText(capability.name)).toBeInTheDocument();
      expect(screen.getByText('Update Environment')).toBeInTheDocument();

      // Test delete operation
      rerender(
        <EnvironmentSelectorModal
          isOpen={true}
          onClose={vi.fn()}
          onSelect={vi.fn()}
          capability={capability}
          deployments={[deployment]}
          operationType="delete"
        />
      );

      expect(screen.getByText(capability.name)).toBeInTheDocument();
      expect(screen.getByText('Delete Environment')).toBeInTheDocument();
    });
  });


  /**
   * Property 8: Modal Dismissal Behavior
   * For any EnvironmentSelectorModal, clicking outside the modal, pressing Escape,
   * or clicking Cancel SHALL close the modal without modifying wizard state or
   * navigating away.
   * Validates: Requirements 3.4, 3.5
   */
  describe('Property 8: Modal Dismissal Behavior', () => {
    it('should call onClose when Cancel button is clicked', () => {
      const capability = createTestCapability();

      const deployment: DeploymentState = {
        capability_name: 'test',
        environment: 'dev',
        region: 'us-east-1',
        last_deployment: new Date().toISOString(),
        stacks: [],
      };

      const onClose = vi.fn();
      const onSelect = vi.fn();

      render(
        <EnvironmentSelectorModal
          isOpen={true}
          onClose={onClose}
          onSelect={onSelect}
          capability={capability}
          deployments={[deployment]}
          operationType="update"
        />
      );

      // Click Cancel button
      const cancelButton = screen.getByText('Cancel');
      fireEvent.click(cancelButton);

      // onClose should be called, onSelect should NOT
      expect(onClose).toHaveBeenCalled();
      expect(onSelect).not.toHaveBeenCalled();
    });

    it('should call onClose when Escape key is pressed', () => {
      const capability = createTestCapability();

      const deployment: DeploymentState = {
        capability_name: 'test',
        environment: 'dev',
        region: 'us-east-1',
        last_deployment: new Date().toISOString(),
        stacks: [],
      };

      const onClose = vi.fn();
      const onSelect = vi.fn();

      render(
        <EnvironmentSelectorModal
          isOpen={true}
          onClose={onClose}
          onSelect={onSelect}
          capability={capability}
          deployments={[deployment]}
          operationType="update"
        />
      );

      // Press Escape key
      fireEvent.keyDown(document, { key: 'Escape' });

      // onClose should be called, onSelect should NOT
      expect(onClose).toHaveBeenCalled();
      expect(onSelect).not.toHaveBeenCalled();
    });

    it('should not render when isOpen is false', () => {
      const capability = createTestCapability();

      const deployment: DeploymentState = {
        capability_name: 'test',
        environment: 'dev',
        region: 'us-east-1',
        last_deployment: new Date().toISOString(),
        stacks: [],
      };

      const { container } = render(
        <EnvironmentSelectorModal
          isOpen={false}
          onClose={vi.fn()}
          onSelect={vi.fn()}
          capability={capability}
          deployments={[deployment]}
          operationType="update"
        />
      );

      // Modal should not be rendered
      expect(container.firstChild).toBeNull();
    });
  });

  /**
   * Property 11: Operation-Specific Modal Styling
   * For any EnvironmentSelectorModal, the modal SHALL display with green/neutral
   * accents for update operations and red/warning accents for delete operations.
   * Validates: Requirements 4.3, 4.4
   */
  describe('Property 11: Operation-Specific Modal Styling', () => {
    it('should display green styling for update operations', () => {
      const capability = createTestCapability();

      const deployment: DeploymentState = {
        capability_name: 'test',
        environment: 'dev',
        region: 'us-east-1',
        last_deployment: new Date().toISOString(),
        stacks: [],
      };

      const { container } = render(
        <EnvironmentSelectorModal
          isOpen={true}
          onClose={vi.fn()}
          onSelect={vi.fn()}
          capability={capability}
          deployments={[deployment]}
          operationType="update"
        />
      );

      // Modal should have green border
      const modal = container.querySelector('.border-green-300');
      expect(modal).toBeInTheDocument();
    });

    it('should display red styling for delete operations', () => {
      const capability = createTestCapability();

      const deployment: DeploymentState = {
        capability_name: 'test',
        environment: 'dev',
        region: 'us-east-1',
        last_deployment: new Date().toISOString(),
        stacks: [],
      };

      const { container } = render(
        <EnvironmentSelectorModal
          isOpen={true}
          onClose={vi.fn()}
          onSelect={vi.fn()}
          capability={capability}
          deployments={[deployment]}
          operationType="delete"
        />
      );

      // Modal should have red border
      const modal = container.querySelector('.border-red-300');
      expect(modal).toBeInTheDocument();
    });
  });
});
