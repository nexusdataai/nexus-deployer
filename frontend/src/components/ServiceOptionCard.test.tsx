/**
 * Unit tests for ServiceOptionCard component
 * Tests rendering, selection, disabled states, and accessibility
 * **Feature: aws-architecture-selection**
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import * as fc from 'fast-check';
import ServiceOptionCard from './ServiceOptionCard';
import { ServiceOptionMeta, CostTier } from '../types/architecture';

// Helper to create a service option
const createServiceOption = (
  overrides: Partial<ServiceOptionMeta> = {}
): ServiceOptionMeta => ({
  id: 'test_service',
  name: 'Test Service',
  description: 'A test service description',
  icon: 'ecs',
  availability: 'available',
  costTier: 'medium',
  features: ['Feature 1', 'Feature 2', 'Feature 3'],
  ...overrides,
});

describe('ServiceOptionCard', () => {
  const mockOnSelect = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Basic Rendering', () => {
    it('should render service name', () => {
      const option = createServiceOption({ name: 'ECS (Fargate)' });
      render(<ServiceOptionCard option={option} isSelected={false} onSelect={mockOnSelect} />);
      
      expect(screen.getByText('ECS (Fargate)')).toBeInTheDocument();
    });

    it('should render service description', () => {
      const option = createServiceOption({ description: 'Serverless containers' });
      render(<ServiceOptionCard option={option} isSelected={false} onSelect={mockOnSelect} />);
      
      expect(screen.getByText('Serverless containers')).toBeInTheDocument();
    });

    it('should render cost tier indicator for low cost', () => {
      const option = createServiceOption({ costTier: 'low' });
      render(<ServiceOptionCard option={option} isSelected={false} onSelect={mockOnSelect} />);
      
      expect(screen.getByText('$')).toBeInTheDocument();
    });

    it('should render cost tier indicator for medium cost', () => {
      const option = createServiceOption({ costTier: 'medium' });
      render(<ServiceOptionCard option={option} isSelected={false} onSelect={mockOnSelect} />);
      
      expect(screen.getByText('$$')).toBeInTheDocument();
    });

    it('should render cost tier indicator for high cost', () => {
      const option = createServiceOption({ costTier: 'high' });
      render(<ServiceOptionCard option={option} isSelected={false} onSelect={mockOnSelect} />);
      
      expect(screen.getByText('$$$')).toBeInTheDocument();
    });

    it('should render feature tags', () => {
      const option = createServiceOption({ features: ['Auto-scaling', 'Load balancing'] });
      render(<ServiceOptionCard option={option} isSelected={false} onSelect={mockOnSelect} />);
      
      expect(screen.getByText('Auto-scaling')).toBeInTheDocument();
      expect(screen.getByText('Load balancing')).toBeInTheDocument();
    });

    it('should show "+N more" when more than 3 features', () => {
      const option = createServiceOption({ 
        features: ['Feature 1', 'Feature 2', 'Feature 3', 'Feature 4', 'Feature 5'] 
      });
      render(<ServiceOptionCard option={option} isSelected={false} onSelect={mockOnSelect} />);
      
      expect(screen.getByText('+2 more')).toBeInTheDocument();
    });
  });

  describe('Selection State', () => {
    /**
     * Test that selected card has visual highlight
     * **Validates: Requirements 2.4, 3.5**
     */
    it('should apply selection highlight when selected', () => {
      const option = createServiceOption();
      const { container } = render(
        <ServiceOptionCard option={option} isSelected={true} onSelect={mockOnSelect} />
      );
      
      const card = container.firstChild as HTMLElement;
      expect(card).toHaveClass('border-blue-500');
      expect(card).toHaveClass('bg-blue-50');
    });

    it('should not apply selection highlight when not selected', () => {
      const option = createServiceOption();
      const { container } = render(
        <ServiceOptionCard option={option} isSelected={false} onSelect={mockOnSelect} />
      );
      
      const card = container.firstChild as HTMLElement;
      expect(card).not.toHaveClass('border-blue-500');
      expect(card).not.toHaveClass('bg-blue-50');
    });

    it('should show checkmark icon when selected', () => {
      const option = createServiceOption();
      render(<ServiceOptionCard option={option} isSelected={true} onSelect={mockOnSelect} />);
      
      // Check for SVG checkmark
      const svg = document.querySelector('svg.text-blue-500');
      expect(svg).toBeInTheDocument();
    });
  });

  describe('Click Behavior', () => {
    /**
     * Test that clicking available option triggers onSelect
     * **Validates: Requirements 2.4, 3.5**
     */
    it('should call onSelect when clicked on available option', () => {
      const option = createServiceOption({ availability: 'available' });
      render(<ServiceOptionCard option={option} isSelected={false} onSelect={mockOnSelect} />);
      
      const card = screen.getByRole('button');
      fireEvent.click(card);
      
      expect(mockOnSelect).toHaveBeenCalledTimes(1);
    });

    it('should support keyboard selection with Enter', () => {
      const option = createServiceOption({ availability: 'available' });
      render(<ServiceOptionCard option={option} isSelected={false} onSelect={mockOnSelect} />);
      
      const card = screen.getByRole('button');
      fireEvent.keyDown(card, { key: 'Enter' });
      
      expect(mockOnSelect).toHaveBeenCalledTimes(1);
    });

    it('should support keyboard selection with Space', () => {
      const option = createServiceOption({ availability: 'available' });
      render(<ServiceOptionCard option={option} isSelected={false} onSelect={mockOnSelect} />);
      
      const card = screen.getByRole('button');
      fireEvent.keyDown(card, { key: ' ' });
      
      expect(mockOnSelect).toHaveBeenCalledTimes(1);
    });
  });

  describe('Disabled State (Coming Soon)', () => {
    /**
     * Test that coming_soon options show badge
     * **Validates: Requirements 6.4**
     */
    it('should show "Coming Soon" badge for disabled options', () => {
      const option = createServiceOption({ availability: 'coming_soon' });
      render(<ServiceOptionCard option={option} isSelected={false} onSelect={mockOnSelect} />);
      
      expect(screen.getByText('Coming Soon')).toBeInTheDocument();
    });

    /**
     * Test that clicking disabled option does NOT trigger onSelect
     * **Validates: Requirements 2.3, 3.3, 3.4**
     */
    it('should NOT call onSelect when clicked on coming_soon option', () => {
      const option = createServiceOption({ availability: 'coming_soon' });
      render(<ServiceOptionCard option={option} isSelected={false} onSelect={mockOnSelect} />);
      
      const card = screen.getByRole('button');
      fireEvent.click(card);
      
      expect(mockOnSelect).not.toHaveBeenCalled();
    });

    it('should apply reduced opacity for disabled options', () => {
      const option = createServiceOption({ availability: 'coming_soon' });
      const { container } = render(
        <ServiceOptionCard option={option} isSelected={false} onSelect={mockOnSelect} />
      );
      
      const card = container.firstChild as HTMLElement;
      expect(card).toHaveClass('opacity-60');
    });

    it('should have cursor-not-allowed for disabled options', () => {
      const option = createServiceOption({ availability: 'coming_soon' });
      const { container } = render(
        <ServiceOptionCard option={option} isSelected={false} onSelect={mockOnSelect} />
      );
      
      const card = container.firstChild as HTMLElement;
      expect(card).toHaveClass('cursor-not-allowed');
    });

    it('should have aria-disabled=true for disabled options', () => {
      const option = createServiceOption({ availability: 'coming_soon' });
      render(<ServiceOptionCard option={option} isSelected={false} onSelect={mockOnSelect} />);
      
      const card = screen.getByRole('button');
      expect(card).toHaveAttribute('aria-disabled', 'true');
    });
  });
});

describe('Property-Based Tests: ServiceOptionCard', () => {
  /**
   * Property 5: Disabled Service Non-Selectability
   * For any ServiceOption with availability equal to 'coming_soon',
   * any click action on that option SHALL NOT modify state.
   * **Feature: aws-architecture-selection, Property 5: Disabled Service Non-Selectability**
   * **Validates: Requirements 2.3, 3.3, 3.4**
   */
  it('Property 5: Disabled services are never selectable', () => {
    fc.assert(
      fc.property(
        fc.record({
          id: fc.string({ minLength: 1, maxLength: 20 }),
          name: fc.string({ minLength: 1, maxLength: 50 }),
          description: fc.string({ minLength: 1, maxLength: 200 }),
          icon: fc.constantFrom('ecs', 'eks', 'ec2', 'cloudfront', 'amplify'),
          costTier: fc.constantFrom('low', 'medium', 'high') as fc.Arbitrary<CostTier>,
          features: fc.array(fc.string({ minLength: 1, maxLength: 30 }), { minLength: 1, maxLength: 5 }),
        }),
        (partialOption) => {
          const mockOnSelect = vi.fn();
          const option: ServiceOptionMeta = {
            ...partialOption,
            availability: 'coming_soon', // Always disabled
          };
          
          render(<ServiceOptionCard option={option} isSelected={false} onSelect={mockOnSelect} />);
          
          const card = screen.getByRole('button');
          fireEvent.click(card);
          
          // Property: onSelect should NEVER be called for disabled options
          const result = mockOnSelect.mock.calls.length === 0;
          
          // Cleanup
          document.body.innerHTML = '';
          vi.clearAllMocks();
          
          return result;
        }
      ),
      { numRuns: 50 }
    );
  });

  /**
   * Property: Available services are always selectable
   * For any ServiceOption with availability equal to 'available',
   * clicking the option SHALL trigger onSelect.
   * **Validates: Requirements 2.4, 3.5**
   */
  it('Property: Available services are always selectable', () => {
    fc.assert(
      fc.property(
        fc.record({
          id: fc.string({ minLength: 1, maxLength: 20 }),
          name: fc.string({ minLength: 1, maxLength: 50 }),
          description: fc.string({ minLength: 1, maxLength: 200 }),
          icon: fc.constantFrom('ecs', 'eks', 'ec2', 'cloudfront', 'amplify'),
          costTier: fc.constantFrom('low', 'medium', 'high') as fc.Arbitrary<CostTier>,
          features: fc.array(fc.string({ minLength: 1, maxLength: 30 }), { minLength: 1, maxLength: 5 }),
        }),
        (partialOption) => {
          const mockOnSelect = vi.fn();
          const option: ServiceOptionMeta = {
            ...partialOption,
            availability: 'available', // Always available
          };
          
          render(<ServiceOptionCard option={option} isSelected={false} onSelect={mockOnSelect} />);
          
          const card = screen.getByRole('button');
          fireEvent.click(card);
          
          // Property: onSelect should ALWAYS be called for available options
          const result = mockOnSelect.mock.calls.length === 1;
          
          // Cleanup
          document.body.innerHTML = '';
          vi.clearAllMocks();
          
          return result;
        }
      ),
      { numRuns: 50 }
    );
  });
});
