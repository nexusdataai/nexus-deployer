/**
 * Tests for CapabilitySelection component - Environment-specific operations
 * Feature: environment-specific-operations
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// Mock the wizard context
const mockSetCapability = vi.fn();
const mockSetStep = vi.fn();
const mockSetEnvironment = vi.fn();
const mockSetAwsRegion = vi.fn();
const mockSetDeleteMode = vi.fn();

vi.mock('../context/WizardContext', () => ({
  useWizard: () => ({
    setCapability: mockSetCapability,
    setStep: mockSetStep,
    setEnvironment: mockSetEnvironment,
    setAwsRegion: mockSetAwsRegion,
    setDeleteMode: mockSetDeleteMode,
  }),
}));

// Mock the API
vi.mock('../services/api', () => ({
  capabilityApi: {
    getAll: vi.fn().mockResolvedValue([
      {
        id: '1',
        name: 'Test Capability',
        description: 'Test description',
        version: '1.0.0',
        category: 'Test',
        status: 'available',
        estimated_deployment_time: 10,
      },
    ]),
  },
  deploymentApi: {
    getDeploymentStates: vi.fn().mockResolvedValue({ deployments: [] }),
  },
}));

// Import after mocks
import CapabilitySelection from './CapabilitySelection';
import { deploymentApi } from '../services/api';

describe('CapabilitySelection - Environment-specific operations', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });


  /**
   * Property 1: Modal Display for Multi-Deployment Capabilities
   * For any installed capability with more than one deployment, clicking either
   * Update or Delete SHALL display the EnvironmentSelectorModal with all
   * deployments listed.
   * Validates: Requirements 1.1, 2.1
   */
  describe('Property 1: Modal Display for Multi-Deployment Capabilities', () => {
    it('should show modal when Update is clicked on capability with multiple deployments', async () => {
      const multipleDeployments = [
        {
          capability_name: 'Test Capability',
          environment: 'prod',
          region: 'us-east-1',
          last_deployment: new Date().toISOString(),
          stacks: [],
        },
        {
          capability_name: 'Test Capability',
          environment: 'dev',
          region: 'us-west-2',
          last_deployment: new Date().toISOString(),
          stacks: [],
        },
      ];

      vi.mocked(deploymentApi.getDeploymentStates).mockResolvedValue({
        deployments: multipleDeployments,
      });

      render(<CapabilitySelection />);

      // Wait for loading to complete
      await waitFor(() => {
        expect(screen.queryByText('Loading capabilities...')).not.toBeInTheDocument();
      });

      // Find and click Update button
      const updateButton = await screen.findByText('Update');
      fireEvent.click(updateButton);

      // Modal should be displayed
      await waitFor(() => {
        expect(screen.getByText('Update Environment')).toBeInTheDocument();
      });

      // Both environments should be listed in the modal (use getAllByText since they appear in both card and modal)
      const prodElements = screen.getAllByText('PROD');
      const devElements = screen.getAllByText('DEV');
      expect(prodElements.length).toBeGreaterThanOrEqual(2); // One in card, one in modal
      expect(devElements.length).toBeGreaterThanOrEqual(2);
    });

    it('should show modal when Delete is clicked on capability with multiple deployments', async () => {
      const multipleDeployments = [
        {
          capability_name: 'Test Capability',
          environment: 'prod',
          region: 'us-east-1',
          last_deployment: new Date().toISOString(),
          stacks: [],
        },
        {
          capability_name: 'Test Capability',
          environment: 'dev',
          region: 'us-west-2',
          last_deployment: new Date().toISOString(),
          stacks: [],
        },
      ];

      vi.mocked(deploymentApi.getDeploymentStates).mockResolvedValue({
        deployments: multipleDeployments,
      });

      render(<CapabilitySelection />);

      // Wait for loading to complete
      await waitFor(() => {
        expect(screen.queryByText('Loading capabilities...')).not.toBeInTheDocument();
      });

      // Find and click Delete button
      const deleteButton = await screen.findByText('Delete');
      fireEvent.click(deleteButton);

      // Modal should be displayed with delete styling
      await waitFor(() => {
        expect(screen.getByText('Delete Environment')).toBeInTheDocument();
      });

      // Both environments should be listed
      const prodElements = screen.getAllByText('PROD');
      const devElements = screen.getAllByText('DEV');
      expect(prodElements.length).toBeGreaterThanOrEqual(2);
      expect(devElements.length).toBeGreaterThanOrEqual(2);
    });
  });

  /**
   * Property 4: Single Deployment Skips Modal
   * For any installed capability with exactly one deployment, clicking Update
   * or Delete SHALL proceed directly to AWS Configuration without displaying
   * the EnvironmentSelectorModal, using that deployment's environment and region.
   * Validates: Requirements 1.4, 2.4
   */
  describe('Property 4: Single Deployment Skips Modal', () => {
    it('should skip modal and proceed directly when Update is clicked on single deployment', async () => {
      const singleDeployment = [
        {
          capability_name: 'Test Capability',
          environment: 'dev',
          region: 'us-west-2',
          last_deployment: new Date().toISOString(),
          stacks: [],
        },
      ];

      vi.mocked(deploymentApi.getDeploymentStates).mockResolvedValue({
        deployments: singleDeployment,
      });

      render(<CapabilitySelection />);

      // Wait for loading to complete
      await waitFor(() => {
        expect(screen.queryByText('Loading capabilities...')).not.toBeInTheDocument();
      });

      // Find and click Update button
      const updateButton = await screen.findByText('Update');
      fireEvent.click(updateButton);

      // Modal should NOT be displayed
      expect(screen.queryByText('Update Environment')).not.toBeInTheDocument();

      // Wizard context should be set directly
      expect(mockSetEnvironment).toHaveBeenCalledWith('dev');
      expect(mockSetAwsRegion).toHaveBeenCalledWith('us-west-2');
      expect(mockSetDeleteMode).toHaveBeenCalledWith(false);
    });

    it('should skip modal and proceed directly when Delete is clicked on single deployment', async () => {
      const singleDeployment = [
        {
          capability_name: 'Test Capability',
          environment: 'dev',
          region: 'us-west-2',
          last_deployment: new Date().toISOString(),
          stacks: [],
        },
      ];

      vi.mocked(deploymentApi.getDeploymentStates).mockResolvedValue({
        deployments: singleDeployment,
      });

      render(<CapabilitySelection />);

      // Wait for loading to complete
      await waitFor(() => {
        expect(screen.queryByText('Loading capabilities...')).not.toBeInTheDocument();
      });

      // Find and click Delete button
      const deleteButton = await screen.findByText('Delete');
      fireEvent.click(deleteButton);

      // Modal should NOT be displayed
      expect(screen.queryByText('Delete Environment')).not.toBeInTheDocument();

      // Wizard context should be set directly with delete mode
      expect(mockSetEnvironment).toHaveBeenCalledWith('dev');
      expect(mockSetAwsRegion).toHaveBeenCalledWith('us-west-2');
      expect(mockSetDeleteMode).toHaveBeenCalledWith(true);
    });
  });


  /**
   * Property 3: Environment Selection Sets Correct Wizard State
   * For any deployment selected from the EnvironmentSelectorModal, the wizard
   * context SHALL be set with that deployment's environment, region, and the
   * correct delete mode (true for delete, false for update).
   * Validates: Requirements 1.3, 2.3
   */
  describe('Property 3: Environment Selection Sets Correct Wizard State', () => {
    it('should set correct wizard state when environment is selected for update', async () => {
      const multipleDeployments = [
        {
          capability_name: 'Test Capability',
          environment: 'prod',
          region: 'us-east-1',
          last_deployment: new Date().toISOString(),
          stacks: [],
        },
        {
          capability_name: 'Test Capability',
          environment: 'dev',
          region: 'us-west-2',
          last_deployment: new Date().toISOString(),
          stacks: [],
        },
      ];

      vi.mocked(deploymentApi.getDeploymentStates).mockResolvedValue({
        deployments: multipleDeployments,
      });

      render(<CapabilitySelection />);

      // Wait for loading to complete
      await waitFor(() => {
        expect(screen.queryByText('Loading capabilities...')).not.toBeInTheDocument();
      });

      // Click Update to open modal
      const updateButton = await screen.findByText('Update');
      fireEvent.click(updateButton);

      // Wait for modal
      await waitFor(() => {
        expect(screen.getByText('Update Environment')).toBeInTheDocument();
      });

      // Select DEV environment - find the one in the modal (has blue styling)
      const devButtons = screen.getAllByText('DEV');
      // The modal button has the blue-700 class
      const modalDevButton = devButtons.find(el => 
        el.closest('button')?.className.includes('border-blue')
      )?.closest('button');
      fireEvent.click(modalDevButton!);

      // Wizard state should be set correctly
      expect(mockSetEnvironment).toHaveBeenCalledWith('dev');
      expect(mockSetAwsRegion).toHaveBeenCalledWith('us-west-2');
      expect(mockSetDeleteMode).toHaveBeenCalledWith(false);
    });

    it('should set correct wizard state when environment is selected for delete', async () => {
      const multipleDeployments = [
        {
          capability_name: 'Test Capability',
          environment: 'prod',
          region: 'us-east-1',
          last_deployment: new Date().toISOString(),
          stacks: [],
        },
        {
          capability_name: 'Test Capability',
          environment: 'dev',
          region: 'us-west-2',
          last_deployment: new Date().toISOString(),
          stacks: [],
        },
      ];

      vi.mocked(deploymentApi.getDeploymentStates).mockResolvedValue({
        deployments: multipleDeployments,
      });

      render(<CapabilitySelection />);

      // Wait for loading to complete
      await waitFor(() => {
        expect(screen.queryByText('Loading capabilities...')).not.toBeInTheDocument();
      });

      // Click Delete to open modal
      const deleteButton = await screen.findByText('Delete');
      fireEvent.click(deleteButton);

      // Wait for modal
      await waitFor(() => {
        expect(screen.getByText('Delete Environment')).toBeInTheDocument();
      });

      // Select DEV environment (non-prod, no confirmation needed)
      const devButtons = screen.getAllByText('DEV');
      const modalDevButton = devButtons.find(el => 
        el.closest('button')?.className.includes('border-blue')
      )?.closest('button');
      fireEvent.click(modalDevButton!);

      // Wizard state should be set correctly with delete mode
      expect(mockSetEnvironment).toHaveBeenCalledWith('dev');
      expect(mockSetAwsRegion).toHaveBeenCalledWith('us-west-2');
      expect(mockSetDeleteMode).toHaveBeenCalledWith(true);
    });
  });

  /**
   * Property 10: Selection Highlighting
   * For any deployment card that is hovered or focused in the EnvironmentSelectorModal,
   * the card SHALL display a distinct highlight style to indicate interactivity.
   * Validates: Requirements 4.1
   */
  describe('Property 10: Selection Highlighting', () => {
    it('should have hover styles on deployment cards', async () => {
      const multipleDeployments = [
        {
          capability_name: 'Test Capability',
          environment: 'prod',
          region: 'us-east-1',
          last_deployment: new Date().toISOString(),
          stacks: [],
        },
        {
          capability_name: 'Test Capability',
          environment: 'dev',
          region: 'us-west-2',
          last_deployment: new Date().toISOString(),
          stacks: [],
        },
      ];

      vi.mocked(deploymentApi.getDeploymentStates).mockResolvedValue({
        deployments: multipleDeployments,
      });

      render(<CapabilitySelection />);

      // Wait for loading to complete
      await waitFor(() => {
        expect(screen.queryByText('Loading capabilities...')).not.toBeInTheDocument();
      });

      // Click Update to open modal
      const updateButton = await screen.findByText('Update');
      fireEvent.click(updateButton);

      // Wait for modal
      await waitFor(() => {
        expect(screen.getByText('Update Environment')).toBeInTheDocument();
      });

      // Check that deployment cards have hover classes
      const devButtons = screen.getAllByText('DEV');
      const modalDevButton = devButtons.find(el => 
        el.closest('button')?.className.includes('border-blue')
      )?.closest('button');
      expect(modalDevButton?.className).toContain('hover:');
    });
  });
});
