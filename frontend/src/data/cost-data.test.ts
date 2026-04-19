/**
 * Property-Based Tests for Cost Estimation
 * Feature: iam-permission-documentation
 */
import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import { calculateTotalCost, COST_ESTIMATES, formatCost } from './cost-data';

describe('Cost Estimation - Property Tests', () => {
  /**
   * Property 4: Environment-Specific Cost Estimation
   * For any two different environment selections (dev vs prod), the cost estimation
   * SHALL return different total cost ranges, with production estimates being
   * greater than or equal to development estimates.
   * 
   * Validates: Requirements 5.3
   */
  describe('Property 4: Environment-Specific Cost Estimation', () => {
    it('production costs are always >= development costs', () => {
      fc.assert(
        fc.property(fc.boolean(), (enableNAT) => {
          const devCost = calculateTotalCost('dev', enableNAT);
          const prodCost = calculateTotalCost('prod', enableNAT);
          
          // Production min should be >= dev min
          expect(prodCost.min).toBeGreaterThanOrEqual(devCost.min);
          
          // Production max should be >= dev max
          expect(prodCost.max).toBeGreaterThanOrEqual(devCost.max);
        }),
        { numRuns: 100 }
      );
    });

    it('staging costs are between dev and prod costs', () => {
      fc.assert(
        fc.property(fc.boolean(), (enableNAT) => {
          const devCost = calculateTotalCost('dev', enableNAT);
          const stageCost = calculateTotalCost('stage', enableNAT);
          const prodCost = calculateTotalCost('prod', enableNAT);
          
          // Staging min should be >= dev min
          expect(stageCost.min).toBeGreaterThanOrEqual(devCost.min);
          
          // Staging max should be <= prod max
          expect(stageCost.max).toBeLessThanOrEqual(prodCost.max);
        }),
        { numRuns: 100 }
      );
    });

    it('NAT Gateway increases total cost when enabled', () => {
      const environments: ('dev' | 'stage' | 'prod')[] = ['dev', 'stage', 'prod'];
      
      for (const env of environments) {
        const withoutNAT = calculateTotalCost(env, false);
        const withNAT = calculateTotalCost(env, true);
        
        // With NAT should always be more expensive
        expect(withNAT.min).toBeGreaterThan(withoutNAT.min);
        expect(withNAT.max).toBeGreaterThan(withoutNAT.max);
      }
    });

    it('cost breakdown contains all included resources', () => {
      fc.assert(
        fc.property(
          fc.constantFrom('dev', 'stage', 'prod') as fc.Arbitrary<'dev' | 'stage' | 'prod'>,
          fc.boolean(),
          (env, enableNAT) => {
            const result = calculateTotalCost(env, enableNAT);
            
            // Breakdown should not be empty
            expect(result.breakdown.length).toBeGreaterThan(0);
            
            // Sum of breakdown should equal totals
            let breakdownMin = 0;
            let breakdownMax = 0;
            for (const item of result.breakdown) {
              breakdownMin += item.monthlyCostMin;
              breakdownMax += item.monthlyCostMax;
            }
            
            expect(result.min).toBe(breakdownMin);
            expect(result.max).toBe(breakdownMax);
          }
        ),
        { numRuns: 100 }
      );
    });

    it('all cost estimates have valid pricing links', () => {
      const environments: ('dev' | 'stage' | 'prod')[] = ['dev', 'stage', 'prod'];
      
      for (const env of environments) {
        const estimates = COST_ESTIMATES[env];
        
        for (const estimate of estimates) {
          // Pricing link should be a valid URL
          expect(estimate.pricingLink).toMatch(/^https:\/\/aws\.amazon\.com\//);
          
          // Resource name should not be empty
          expect(estimate.resource.length).toBeGreaterThan(0);
          
          // Description should not be empty
          expect(estimate.description.length).toBeGreaterThan(0);
          
          // Min cost should be <= max cost
          expect(estimate.monthlyCostMin).toBeLessThanOrEqual(estimate.monthlyCostMax);
          
          // Costs should be non-negative
          expect(estimate.monthlyCostMin).toBeGreaterThanOrEqual(0);
          expect(estimate.monthlyCostMax).toBeGreaterThanOrEqual(0);
        }
      }
    });

    it('formatCost produces valid currency strings', () => {
      fc.assert(
        fc.property(fc.integer({ min: 0, max: 10000 }), (amount) => {
          const formatted = formatCost(amount);
          
          // Should start with $
          expect(formatted).toMatch(/^\$/);
          
          // Should contain the number (possibly with commas)
          expect(formatted).toMatch(/\$[\d,]+/);
        }),
        { numRuns: 100 }
      );
    });
  });

  describe('Cost Data Integrity', () => {
    it('all environments have cost estimates defined', () => {
      expect(COST_ESTIMATES.dev).toBeDefined();
      expect(COST_ESTIMATES.stage).toBeDefined();
      expect(COST_ESTIMATES.prod).toBeDefined();
      
      expect(COST_ESTIMATES.dev.length).toBeGreaterThan(0);
      expect(COST_ESTIMATES.stage.length).toBeGreaterThan(0);
      expect(COST_ESTIMATES.prod.length).toBeGreaterThan(0);
    });

    it('NAT Gateway is marked as optional in all environments', () => {
      const environments: ('dev' | 'stage' | 'prod')[] = ['dev', 'stage', 'prod'];
      
      for (const env of environments) {
        const natGateway = COST_ESTIMATES[env].find(e => e.resource === 'NAT Gateway');
        expect(natGateway).toBeDefined();
        expect(natGateway?.isOptional).toBe(true);
      }
    });

    it('production has more resources than development', () => {
      // Production typically has additional resources like WAF
      expect(COST_ESTIMATES.prod.length).toBeGreaterThanOrEqual(COST_ESTIMATES.dev.length);
    });
  });
});
