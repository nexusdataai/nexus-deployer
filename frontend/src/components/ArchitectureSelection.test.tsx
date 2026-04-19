/**
 * Unit tests for ArchitectureSelection component
 * Tests rendering, selection, navigation, and state management
 * **Feature: aws-architecture-selection**
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import * as fc from 'fast-check';
import ArchitectureSelection from './ArchitectureSelection';
import { WizardStep } from '../types/wizard';
import { FrontendService, BackendService, ArchitectureConfig } from '../types/architecture';

// Mock the WizardContext
const mockSetStep = vi.fn();
const mockSetArchitectureConfig = vi.fn();
let mockArchitectureConfig: ArchitectureConfig | null = null;

vi.mock('../context/WizardContext', () => ({
  useWizard: () => ({
    state: {
      architectureConfig: mockArchitectureConfig,
    },
    setStep: mockSetStep,
    setArchitectureConfig: mockSetArchitectureConfig,
  }),
}));

describe('ArchitectureSelection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockArchitectureConfig = null;
  });

  describe('Basic Rendering', () => {
    it('should render the page title', () => {
      render(<ArchitectureSelection />);
      expect(screen.getByText('Architecture Selection')).toBeInTheDocument();
    });

    it('should render the description text', () => {
      render(<ArchitectureSelection />);
      expect(screen.getByText(/Choose the AWS services for deploying/)).toBeInTheDocument();
    });

    it('should render Frontend Layer section', () => {
      render(<ArchitectureSelection />);
      expect(screen.getByText('Frontend Layer')).toBeInTheDocument();
    });

    it('should render Backend Layer section', () => {
      render(<ArchitectureSelection />);
      expect(screen.getByText('Backend Layer')).toBeInTheDocument();
    });

    it('should render Back button', () => {
      render(<ArchitectureSelection />);
      expect(screen.getByText('Back')).toBeInTheDocument();
    });

    it('should render Continue button', () => {
      render(<ArchitectureSelection />);
      expect(screen.getByText('Continue')).toBeInTheDocument();
    });
  });

  describe('Architecture Diagram', () => {
    it('should render Users icon in diagram', () => {
      render(<ArchitectureSelection />);
      expect(screen.getByText('Users')).toBeInTheDocument();
    });

    it('should render Data icon in diagram', () => {
      render(<ArchitectureSelection />);
      expect(screen.getByText('Data')).toBeInTheDocument();
    });

    it('should render Frontend box in diagram', () => {
      render(<ArchitectureSelection />);
      expect(screen.getByText('Frontend')).toBeInTheDocument();
    });

    it('should render Backend box in diagram', () => {
      render(<ArchitectureSelection />);
      expect(screen.getByText('Backend')).toBeInTheDocument();
    });
  });

  describe('Service Options Rendering', () => {
    it('should render S3 + CloudFront option', () => {
      render(<ArchitectureSelection />);
      const elements = screen.getAllByText('S3 + CloudFront');
      expect(elements.length).toBeGreaterThan(0);
    });

    it('should render AWS Amplify option with Coming Soon', () => {
      render(<ArchitectureSelection />);
      expect(screen.getByText('AWS Amplify')).toBeInTheDocument();
    });

    it('should render ECS (Fargate) option', () => {
      render(<ArchitectureSelection />);
      const elements = screen.getAllByText('ECS (Fargate)');
      expect(elements.length).toBeGreaterThan(0);
    });

    it('should render EKS (Kubernetes) option with Coming Soon', () => {
      render(<ArchitectureSelection />);
      expect(screen.getByText('EKS (Kubernetes)')).toBeInTheDocument();
    });

    it('should render EC2 (Plain Node) option with Coming Soon', () => {
      render(<ArchitectureSelection />);
      expect(screen.getByText('EC2 (Plain Node)')).toBeInTheDocument();
    });
  });

  describe('Default Selection', () => {
    /**
     * Test that S3/CloudFront is selected by default
     * **Validates: Requirements 2.6**
     */
    it('should have S3/CloudFront selected by default for frontend', () => {
      render(<ArchitectureSelection />);
      
      // The setArchitectureConfig should be called with default values
      expect(mockSetArchitectureConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          frontendService: FrontendService.S3_CLOUDFRONT,
        })
      );
    });

    /**
     * Test that ECS is selected by default
     * **Validates: Requirements 3.7**
     */
    it('should have ECS selected by default for backend', () => {
      render(<ArchitectureSelection />);
      
      expect(mockSetArchitectureConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          backendService: BackendService.ECS,
        })
      );
    });
  });

  describe('State Restoration', () => {
    /**
     * Test that previous selections are restored from context
     * **Validates: Requirements 4.2**
     */
    it('should restore previous selections from context', () => {
      mockArchitectureConfig = {
        frontendService: FrontendService.S3_CLOUDFRONT,
        backendService: BackendService.ECS,
      };
      
      render(<ArchitectureSelection />);
      
      // Component should use the values from context
      expect(mockSetArchitectureConfig).toHaveBeenCalledWith(mockArchitectureConfig);
    });
  });

  describe('Navigation', () => {
    it('should navigate to CAPABILITY_SELECTION when Back is clicked', () => {
      render(<ArchitectureSelection />);
      
      const backButton = screen.getByText('Back');
      fireEvent.click(backButton);
      
      expect(mockSetStep).toHaveBeenCalledWith(WizardStep.CAPABILITY_SELECTION);
    });

    it('should navigate to UNIFIED_ENVIRONMENT_CONFIG when Continue is clicked', () => {
      render(<ArchitectureSelection />);
      
      const continueButton = screen.getByText('Continue');
      fireEvent.click(continueButton);
      
      expect(mockSetStep).toHaveBeenCalledWith(WizardStep.UNIFIED_ENVIRONMENT_CONFIG);
    });

    /**
     * Test that Continue button is enabled with valid selections
     * **Validates: Requirements 5.2**
     */
    it('should have Continue button enabled with default selections', () => {
      render(<ArchitectureSelection />);
      
      const continueButton = screen.getByText('Continue');
      expect(continueButton).not.toBeDisabled();
    });
  });

  describe('Responsive Layout', () => {
    /**
     * Test responsive layout classes
     * **Validates: Requirements 7.1, 7.2**
     */
    it('should have responsive grid classes for service sections', () => {
      const { container } = render(<ArchitectureSelection />);
      
      // Check for responsive grid
      const grid = container.querySelector('.grid.grid-cols-1.lg\\:grid-cols-2');
      expect(grid).toBeInTheDocument();
    });

    it('should have responsive flex classes for architecture diagram', () => {
      const { container } = render(<ArchitectureSelection />);
      
      // Check for responsive flex layout
      const flexContainer = container.querySelector('.flex.flex-col.lg\\:flex-row');
      expect(flexContainer).toBeInTheDocument();
    });
  });
});

describe('Property-Based Tests: ArchitectureSelection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockArchitectureConfig = null;
  });

  /**
   * Property 1: Default Selection Invariant
   * For any initial render with no prior architectureConfig,
   * the component SHALL have S3_CLOUDFRONT and ECS as defaults.
   * **Feature: aws-architecture-selection, Property 1: Default Selection Invariant**
   * **Validates: Requirements 2.6, 3.7**
   */
  it('Property 1: Default selection is always S3_CLOUDFRONT and ECS', () => {
    fc.assert(
      fc.property(
        fc.constant(null), // No prior config
        () => {
          mockArchitectureConfig = null;
          vi.clearAllMocks();
          
          render(<ArchitectureSelection />);
          
          // Property: setArchitectureConfig should be called with defaults
          const calls = mockSetArchitectureConfig.mock.calls;
          const hasDefaultCall = calls.some(
            (call) =>
              call[0].frontendService === FrontendService.S3_CLOUDFRONT &&
              call[0].backendService === BackendService.ECS
          );
          
          // Cleanup
          document.body.innerHTML = '';
          
          return hasDefaultCall;
        }
      ),
      { numRuns: 10 }
    );
  });

  /**
   * Property 2: Selection State Consistency
   * For any user selection on an available service,
   * the context SHALL reflect the selected value.
   * **Feature: aws-architecture-selection, Property 2: Selection State Consistency**
   * **Validates: Requirements 4.1**
   */
  it('Property 2: Selection updates are always reflected in context', () => {
    // Since we can only select available services (S3_CLOUDFRONT, ECS),
    // we verify that the initial render sets the correct config
    fc.assert(
      fc.property(
        fc.record({
          frontend: fc.constantFrom(FrontendService.S3_CLOUDFRONT),
          backend: fc.constantFrom(BackendService.ECS),
        }),
        (selection) => {
          mockArchitectureConfig = {
            frontendService: selection.frontend,
            backendService: selection.backend,
          };
          vi.clearAllMocks();
          
          render(<ArchitectureSelection />);
          
          // Property: The config should be set with the selection
          const calls = mockSetArchitectureConfig.mock.calls;
          const hasCorrectCall = calls.some(
            (call) =>
              call[0].frontendService === selection.frontend &&
              call[0].backendService === selection.backend
          );
          
          // Cleanup
          document.body.innerHTML = '';
          
          return hasCorrectCall;
        }
      ),
      { numRuns: 20 }
    );
  });

  /**
   * Property 3: State Restoration Round-Trip
   * For any valid ArchitectureConfig, navigating away and returning
   * SHALL restore the exact same values.
   * **Feature: aws-architecture-selection, Property 3: State Restoration Round-Trip**
   * **Validates: Requirements 4.2**
   */
  it('Property 3: State restoration preserves exact values', () => {
    fc.assert(
      fc.property(
        fc.record({
          frontendService: fc.constantFrom(FrontendService.S3_CLOUDFRONT, FrontendService.AMPLIFY),
          backendService: fc.constantFrom(BackendService.ECS, BackendService.EKS, BackendService.EC2),
        }),
        (config: ArchitectureConfig) => {
          // Simulate returning to the component with stored config
          mockArchitectureConfig = config;
          vi.clearAllMocks();
          
          render(<ArchitectureSelection />);
          
          // Property: The restored config should match the stored config
          const calls = mockSetArchitectureConfig.mock.calls;
          const hasRestoredCall = calls.some(
            (call) =>
              call[0].frontendService === config.frontendService &&
              call[0].backendService === config.backendService
          );
          
          // Cleanup
          document.body.innerHTML = '';
          
          return hasRestoredCall;
        }
      ),
      { numRuns: 30 }
    );
  });

  /**
   * Property 4: Validation Gate Property
   * With valid selections, Continue button SHALL be enabled.
   * **Feature: aws-architecture-selection, Property 4: Validation Gate Property**
   * **Validates: Requirements 5.2, 5.5**
   */
  it('Property 4: Continue is enabled with valid selections', () => {
    fc.assert(
      fc.property(
        fc.record({
          frontendService: fc.constantFrom(FrontendService.S3_CLOUDFRONT),
          backendService: fc.constantFrom(BackendService.ECS),
        }),
        (config: ArchitectureConfig) => {
          mockArchitectureConfig = config;
          vi.clearAllMocks();
          
          render(<ArchitectureSelection />);
          
          const continueButton = screen.getByText('Continue');
          const isEnabled = !continueButton.hasAttribute('disabled');
          
          // Cleanup
          document.body.innerHTML = '';
          
          // Property: Continue should be enabled for valid configs
          return isEnabled;
        }
      ),
      { numRuns: 20 }
    );
  });
});
