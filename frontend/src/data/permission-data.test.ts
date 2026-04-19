/**
 * Property-Based Tests for Permission Data
 * Feature: iam-permission-documentation
 */
import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import {
  PERMISSION_CATEGORIES,
  getAllActions,
  getTotalPermissionCount,
  getPermissionsByService,
  DELETE_PERMISSIONS
} from './permission-data';

describe('Permission Data - Property Tests', () => {
  /**
   * Property 1: Service Category Data Completeness
   * For any service displayed in the IAM Permission Panel, the service object
   * SHALL contain a non-empty service name, a non-empty purpose description,
   * and at least one key action.
   * 
   * Validates: Requirements 1.4
   */
  describe('Property 1: Service Category Data Completeness', () => {
    it('all services have non-empty service name', () => {
      for (const category of PERMISSION_CATEGORIES) {
        for (const service of category.services) {
          expect(service.service).toBeDefined();
          expect(service.service.length).toBeGreaterThan(0);
        }
      }
    });

    it('all services have non-empty purpose description', () => {
      for (const category of PERMISSION_CATEGORIES) {
        for (const service of category.services) {
          expect(service.purpose).toBeDefined();
          expect(service.purpose.length).toBeGreaterThan(0);
        }
      }
    });

    it('all services have at least one key action', () => {
      for (const category of PERMISSION_CATEGORIES) {
        for (const service of category.services) {
          expect(service.keyActions).toBeDefined();
          expect(Array.isArray(service.keyActions)).toBe(true);
          expect(service.keyActions.length).toBeGreaterThan(0);
        }
      }
    });

    it('all services have at least one action in allActions', () => {
      for (const category of PERMISSION_CATEGORIES) {
        for (const service of category.services) {
          expect(service.allActions).toBeDefined();
          expect(Array.isArray(service.allActions)).toBe(true);
          expect(service.allActions.length).toBeGreaterThan(0);
        }
      }
    });

    it('all actions follow AWS action format (service:action)', () => {
      for (const category of PERMISSION_CATEGORIES) {
        for (const service of category.services) {
          for (const action of service.allActions) {
            expect(action).toMatch(/^[a-z0-9-]+:[A-Za-z]+$/);
          }
        }
      }
    });

    it('key actions are subset of all actions (by action name)', () => {
      for (const category of PERMISSION_CATEGORIES) {
        for (const service of category.services) {
          // Extract action names from allActions (part after colon)
          const allActionNames = service.allActions.map(a => {
            const parts = a.split(':');
            return parts[1] || a;
          });
          
          for (const keyAction of service.keyActions) {
            // Key action should appear in allActions (by name)
            expect(allActionNames).toContain(keyAction);
          }
        }
      }
    });
  });

  describe('Category Data Integrity', () => {
    it('all categories have non-empty name', () => {
      for (const category of PERMISSION_CATEGORIES) {
        expect(category.name).toBeDefined();
        expect(category.name.length).toBeGreaterThan(0);
      }
    });

    it('all categories have non-empty description', () => {
      for (const category of PERMISSION_CATEGORIES) {
        expect(category.description).toBeDefined();
        expect(category.description.length).toBeGreaterThan(0);
      }
    });

    it('all categories have at least one service', () => {
      for (const category of PERMISSION_CATEGORIES) {
        expect(category.services).toBeDefined();
        expect(Array.isArray(category.services)).toBe(true);
        expect(category.services.length).toBeGreaterThan(0);
      }
    });

    it('category names are unique', () => {
      const names = PERMISSION_CATEGORIES.map(c => c.name);
      const uniqueNames = new Set(names);
      expect(uniqueNames.size).toBe(names.length);
    });

    it('service names are unique across all categories', () => {
      const serviceNames: string[] = [];
      for (const category of PERMISSION_CATEGORIES) {
        for (const service of category.services) {
          serviceNames.push(service.service);
        }
      }
      const uniqueNames = new Set(serviceNames);
      expect(uniqueNames.size).toBe(serviceNames.length);
    });
  });

  describe('Utility Functions', () => {
    it('getAllActions returns all actions from all categories', () => {
      const allActions = getAllActions();
      
      // Count actions manually
      let expectedCount = 0;
      for (const category of PERMISSION_CATEGORIES) {
        for (const service of category.services) {
          expectedCount += service.allActions.length;
        }
      }
      
      expect(allActions.length).toBe(expectedCount);
    });

    it('getTotalPermissionCount matches getAllActions length', () => {
      const count = getTotalPermissionCount();
      const allActions = getAllActions();
      expect(count).toBe(allActions.length);
    });

    it('getPermissionsByService returns map with all services', () => {
      const map = getPermissionsByService();
      
      // Count services manually
      let expectedServiceCount = 0;
      for (const category of PERMISSION_CATEGORIES) {
        expectedServiceCount += category.services.length;
      }
      
      expect(map.size).toBe(expectedServiceCount);
    });

    it('getPermissionsByService contains correct actions for each service', () => {
      const map = getPermissionsByService();
      
      for (const category of PERMISSION_CATEGORIES) {
        for (const service of category.services) {
          const actions = map.get(service.service);
          expect(actions).toBeDefined();
          expect(actions).toEqual(service.allActions);
        }
      }
    });
  });

  describe('Delete Permissions', () => {
    it('DELETE_PERMISSIONS array is not empty', () => {
      expect(DELETE_PERMISSIONS).toBeDefined();
      expect(Array.isArray(DELETE_PERMISSIONS)).toBe(true);
      expect(DELETE_PERMISSIONS.length).toBeGreaterThan(0);
    });

    it('all delete permissions follow AWS action format', () => {
      for (const action of DELETE_PERMISSIONS) {
        expect(action).toMatch(/^[a-z0-9-]+:[A-Za-z]+$/);
      }
    });

    it('delete permissions include essential delete actions', () => {
      const essentialDeleteActions = [
        'cloudformation:DeleteStack',
        's3:DeleteBucket',
        'ecs:DeleteCluster',
        'dynamodb:DeleteTable'
      ];
      
      for (const action of essentialDeleteActions) {
        expect(DELETE_PERMISSIONS).toContain(action);
      }
    });
  });

  describe('Property-Based Validation', () => {
    it('randomly selected services always have complete data', () => {
      // Flatten all services
      const allServices = PERMISSION_CATEGORIES.flatMap(c => c.services);
      
      fc.assert(
        fc.property(
          fc.integer({ min: 0, max: allServices.length - 1 }),
          (index) => {
            const service = allServices[index];
            
            // Service name is non-empty string
            expect(typeof service.service).toBe('string');
            expect(service.service.length).toBeGreaterThan(0);
            
            // Purpose is non-empty string
            expect(typeof service.purpose).toBe('string');
            expect(service.purpose.length).toBeGreaterThan(0);
            
            // Has at least one key action
            expect(service.keyActions.length).toBeGreaterThan(0);
            
            // Has at least one action
            expect(service.allActions.length).toBeGreaterThan(0);
            
            // All actions are valid format
            for (const action of service.allActions) {
              expect(action).toContain(':');
            }
          }
        ),
        { numRuns: 100 }
      );
    });
  });
});
