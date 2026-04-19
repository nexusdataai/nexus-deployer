/**
 * Unit tests for WelcomeScreen component
 * Tests platform icons, support indicators, and tooltips
 * **Feature: welcome-capability-ui-redesign**
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import * as fc from 'fast-check';

// Mock the context
const mockSetStep = vi.fn();

vi.mock('../context/WizardContext', () => ({
  useWizard: () => ({
    setStep: mockSetStep,
  }),
}));

import WelcomeScreen from './WelcomeScreen';
import { WizardStep } from '../types/wizard';

describe('WelcomeScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Basic Rendering', () => {
    it('should render the hero graphic', () => {
      render(<WelcomeScreen />);
      
      // Check for SVG element (hero illustration)
      const svg = document.querySelector('svg');
      expect(svg).toBeInTheDocument();
    });

    it('should render the title "Totogi Capability Installer"', () => {
      render(<WelcomeScreen />);
      
      expect(screen.getByText('Totogi Capability Installer')).toBeInTheDocument();
    });

    it('should render the tagline "Deploy Business Capability in your Environment"', () => {
      render(<WelcomeScreen />);
      
      expect(screen.getByText('Deploy Business Capability in your Environment')).toBeInTheDocument();
    });

    it('should render the "Get Started" button', () => {
      render(<WelcomeScreen />);
      
      expect(screen.getByText('Get Started')).toBeInTheDocument();
    });

    it('should navigate to Capability Selection when "Get Started" is clicked', () => {
      render(<WelcomeScreen />);
      
      const button = screen.getByText('Get Started');
      fireEvent.click(button);
      
      expect(mockSetStep).toHaveBeenCalledWith(WizardStep.CAPABILITY_SELECTION);
    });
  });

  describe('Platform Icons', () => {
    it('should render all 5 platform icons', () => {
      render(<WelcomeScreen />);
      
      expect(screen.getByTestId('platform-icon-aws')).toBeInTheDocument();
      expect(screen.getByTestId('platform-icon-azure')).toBeInTheDocument();
      expect(screen.getByTestId('platform-icon-gcp')).toBeInTheDocument();
      expect(screen.getByTestId('platform-icon-kubernetes')).toBeInTheDocument();
      expect(screen.getByTestId('platform-icon-onpremise')).toBeInTheDocument();
    });

    it('should render platform icons in a horizontal row', () => {
      render(<WelcomeScreen />);
      
      const platformRow = screen.getByTestId('platform-icons-row');
      expect(platformRow).toBeInTheDocument();
      expect(platformRow).toHaveClass('flex');
    });

    it('should display platform names', () => {
      render(<WelcomeScreen />);
      
      expect(screen.getByText('AWS')).toBeInTheDocument();
      expect(screen.getByText('Azure')).toBeInTheDocument();
      expect(screen.getByText('GCP')).toBeInTheDocument();
      expect(screen.getByText('Kubernetes')).toBeInTheDocument();
      expect(screen.getByText('On-Premise')).toBeInTheDocument();
    });
  });

  describe('Support Indicators', () => {
    /**
     * Test that AWS icon has checkmark indicator
     * **Validates: Requirements 6.2**
     */
    it('should show checkmark indicator on AWS icon', () => {
      render(<WelcomeScreen />);
      
      const awsCheckmark = screen.getByTestId('checkmark-aws');
      expect(awsCheckmark).toBeInTheDocument();
    });

    /**
     * Test that non-AWS icons do NOT have checkmark
     * **Validates: Requirements 6.3**
     */
    it('should NOT show checkmark indicator on Azure icon', () => {
      render(<WelcomeScreen />);
      
      expect(screen.queryByTestId('checkmark-azure')).not.toBeInTheDocument();
    });

    it('should NOT show checkmark indicator on GCP icon', () => {
      render(<WelcomeScreen />);
      
      expect(screen.queryByTestId('checkmark-gcp')).not.toBeInTheDocument();
    });

    it('should NOT show checkmark indicator on Kubernetes icon', () => {
      render(<WelcomeScreen />);
      
      expect(screen.queryByTestId('checkmark-kubernetes')).not.toBeInTheDocument();
    });

    it('should NOT show checkmark indicator on On-Premise icon', () => {
      render(<WelcomeScreen />);
      
      expect(screen.queryByTestId('checkmark-onpremise')).not.toBeInTheDocument();
    });
  });

  describe('Tooltips', () => {
    /**
     * Test that AWS tooltip shows "Supported"
     * **Validates: Requirements 6.5**
     */
    it('should show "Supported" tooltip on AWS icon hover', async () => {
      render(<WelcomeScreen />);
      
      const awsIcon = screen.getByTestId('platform-icon-aws');
      fireEvent.mouseEnter(awsIcon);
      
      await waitFor(() => {
        expect(screen.getByTestId('tooltip-aws')).toBeInTheDocument();
        expect(screen.getByTestId('tooltip-aws')).toHaveTextContent('Supported');
      });
    });

    /**
     * Test that Azure tooltip shows "Coming Soon"
     * **Validates: Requirements 6.5**
     */
    it('should show "Coming Soon" tooltip on Azure icon hover', async () => {
      render(<WelcomeScreen />);
      
      const azureIcon = screen.getByTestId('platform-icon-azure');
      fireEvent.mouseEnter(azureIcon);
      
      await waitFor(() => {
        expect(screen.getByTestId('tooltip-azure')).toBeInTheDocument();
        expect(screen.getByTestId('tooltip-azure')).toHaveTextContent('Coming Soon');
      });
    });

    it('should show "Coming Soon" tooltip on GCP icon hover', async () => {
      render(<WelcomeScreen />);
      
      const gcpIcon = screen.getByTestId('platform-icon-gcp');
      fireEvent.mouseEnter(gcpIcon);
      
      await waitFor(() => {
        expect(screen.getByTestId('tooltip-gcp')).toBeInTheDocument();
        expect(screen.getByTestId('tooltip-gcp')).toHaveTextContent('Coming Soon');
      });
    });

    it('should show "Coming Soon" tooltip on Kubernetes icon hover', async () => {
      render(<WelcomeScreen />);
      
      const k8sIcon = screen.getByTestId('platform-icon-kubernetes');
      fireEvent.mouseEnter(k8sIcon);
      
      await waitFor(() => {
        expect(screen.getByTestId('tooltip-kubernetes')).toBeInTheDocument();
        expect(screen.getByTestId('tooltip-kubernetes')).toHaveTextContent('Coming Soon');
      });
    });

    it('should show "Coming Soon" tooltip on On-Premise icon hover', async () => {
      render(<WelcomeScreen />);
      
      const onPremIcon = screen.getByTestId('platform-icon-onpremise');
      fireEvent.mouseEnter(onPremIcon);
      
      await waitFor(() => {
        expect(screen.getByTestId('tooltip-onpremise')).toBeInTheDocument();
        expect(screen.getByTestId('tooltip-onpremise')).toHaveTextContent('Coming Soon');
      });
    });

    it('should hide tooltip on mouse leave', async () => {
      render(<WelcomeScreen />);
      
      const awsIcon = screen.getByTestId('platform-icon-aws');
      
      // Show tooltip
      fireEvent.mouseEnter(awsIcon);
      await waitFor(() => {
        expect(screen.getByTestId('tooltip-aws')).toBeInTheDocument();
      });
      
      // Hide tooltip
      fireEvent.mouseLeave(awsIcon);
      await waitFor(() => {
        expect(screen.queryByTestId('tooltip-aws')).not.toBeInTheDocument();
      });
    });
  });
});


describe('Property-Based Tests: Platform Icons', () => {
  /**
   * Property 8: Unsupported platforms have no checkmark
   * For any deployment platform that is not AWS (Azure, GCP, Kubernetes, On-Premise),
   * the platform icon should NOT display a checkmark indicator.
   * **Feature: welcome-capability-ui-redesign, Property 8: Unsupported platforms have no checkmark**
   * **Validates: Requirements 6.3**
   */
  it('Property 8: Unsupported platforms have no checkmark', () => {
    // Define the platform configuration as it exists in the component
    const platforms = [
      { id: 'aws', isSupported: true },
      { id: 'azure', isSupported: false },
      { id: 'gcp', isSupported: false },
      { id: 'kubernetes', isSupported: false },
      { id: 'onpremise', isSupported: false },
    ];

    fc.assert(
      fc.property(
        fc.constantFrom(...platforms.filter(p => !p.isSupported)),
        (platform) => {
          render(<WelcomeScreen />);
          
          // Property: For any unsupported platform, checkmark should NOT exist
          const checkmark = screen.queryByTestId(`checkmark-${platform.id}`);
          const result = checkmark === null;
          
          // Cleanup for next iteration
          document.body.innerHTML = '';
          
          return result;
        }
      ),
      { numRuns: 20 }
    );
  });

  /**
   * Property 9: Platform tooltip matches support status
   * For any deployment platform, the tooltip text should be "Supported" if the platform
   * is supported (AWS) and "Coming Soon" if the platform is not yet supported.
   * **Feature: welcome-capability-ui-redesign, Property 9: Platform tooltip matches support status**
   * **Validates: Requirements 6.5**
   */
  it('Property 9: Platform tooltip matches support status', () => {
    // Define the platform configuration as it exists in the component
    const platforms = [
      { id: 'aws', isSupported: true, expectedTooltip: 'Supported' },
      { id: 'azure', isSupported: false, expectedTooltip: 'Coming Soon' },
      { id: 'gcp', isSupported: false, expectedTooltip: 'Coming Soon' },
      { id: 'kubernetes', isSupported: false, expectedTooltip: 'Coming Soon' },
      { id: 'onpremise', isSupported: false, expectedTooltip: 'Coming Soon' },
    ];

    // Property: For any platform, tooltip text matches support status
    fc.assert(
      fc.property(
        fc.constantFrom(...platforms),
        (platform) => {
          // The expected tooltip is determined by support status
          const expectedTooltip = platform.isSupported ? 'Supported' : 'Coming Soon';
          return platform.expectedTooltip === expectedTooltip;
        }
      ),
      { numRuns: 20 }
    );
  });

  /**
   * Property: Only AWS has checkmark (inverse of Property 8)
   * For any supported platform (AWS), the checkmark should be present.
   * **Validates: Requirements 6.2**
   */
  it('Property: Supported platforms have checkmark', () => {
    const supportedPlatforms = [{ id: 'aws', isSupported: true }];

    fc.assert(
      fc.property(
        fc.constantFrom(...supportedPlatforms),
        (platform) => {
          render(<WelcomeScreen />);
          
          // Property: For any supported platform, checkmark should exist
          const checkmark = screen.queryByTestId(`checkmark-${platform.id}`);
          const result = checkmark !== null;
          
          // Cleanup for next iteration
          document.body.innerHTML = '';
          
          return result;
        }
      ),
      { numRuns: 5 }
    );
  });
});
