/**
 * Health Monitor Service
 * 
 * Monitors backend health status with periodic polling.
 * Provides subscription-based notifications for status changes.
 * 
 * Feature: startup-health-check
 * Requirements: 10.2, 10.3, 10.4
 */

import { healthApi, ReadinessResponse } from './api';

export type HealthStatus = 'healthy' | 'degraded' | 'unhealthy' | 'unknown';

export interface HealthState {
  status: HealthStatus;
  ready: boolean;
  phase: string;
  lastCheck: Date | null;
  lastResponseTimeMs: number | null;
  consecutiveFailures: number;
  components: Array<{
    name: string;
    status: string;
    message?: string;
  }>;
  error?: string;
}

export type HealthChangeCallback = (state: HealthState) => void;

const DEFAULT_POLL_INTERVAL_MS = 30000; // 30 seconds
const DEGRADED_RESPONSE_TIME_MS = 2000; // Consider degraded if response > 2s
const MAX_CONSECUTIVE_FAILURES = 3;

/**
 * Health Monitor class
 * Polls backend health endpoint and notifies subscribers of changes
 */
export class HealthMonitor {
  private pollIntervalMs: number;
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private subscribers: Set<HealthChangeCallback> = new Set();
  private currentState: HealthState;
  private isPolling: boolean = false;

  constructor(pollIntervalMs: number = DEFAULT_POLL_INTERVAL_MS) {
    this.pollIntervalMs = pollIntervalMs;
    this.currentState = this.createInitialState();
  }

  private createInitialState(): HealthState {
    return {
      status: 'unknown',
      ready: false,
      phase: 'unknown',
      lastCheck: null,
      lastResponseTimeMs: null,
      consecutiveFailures: 0,
      components: [],
    };
  }

  /**
   * Start polling for health status
   */
  start(): void {
    if (this.pollTimer) {
      return; // Already polling
    }

    // Do an immediate check
    this.checkHealth();

    // Start periodic polling
    this.pollTimer = setInterval(() => {
      this.checkHealth();
    }, this.pollIntervalMs);
  }

  /**
   * Stop polling for health status
   */
  stop(): void {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

  /**
   * Subscribe to health status changes
   * @param callback - Function to call when health status changes
   * @returns Unsubscribe function
   */
  subscribe(callback: HealthChangeCallback): () => void {
    this.subscribers.add(callback);
    
    // Immediately notify with current state
    callback(this.currentState);

    return () => {
      this.subscribers.delete(callback);
    };
  }

  /**
   * Get current health state
   */
  getState(): HealthState {
    return { ...this.currentState };
  }

  /**
   * Force an immediate health check
   */
  async checkHealth(): Promise<HealthState> {
    if (this.isPolling) {
      return this.currentState;
    }

    this.isPolling = true;
    const startTime = Date.now();

    try {
      const response = await healthApi.checkReady();
      const responseTimeMs = Date.now() - startTime;

      const newState = this.processHealthResponse(response, responseTimeMs);
      this.updateState(newState);
      
      return this.currentState;
    } catch (error) {
      const newState = this.processHealthError(error);
      this.updateState(newState);
      
      return this.currentState;
    } finally {
      this.isPolling = false;
    }
  }

  private processHealthResponse(
    response: ReadinessResponse,
    responseTimeMs: number
  ): Partial<HealthState> {
    let status: HealthStatus = 'healthy';

    // Check for degraded status
    if (response.phase === 'DEGRADED') {
      status = 'degraded';
    } else if (!response.ready) {
      status = 'unhealthy';
    } else if (responseTimeMs > DEGRADED_RESPONSE_TIME_MS) {
      status = 'degraded';
    }

    // Check component statuses
    const hasUnhealthyComponent = response.components?.some(
      (c) => c.status === 'unhealthy'
    );
    const hasDegradedComponent = response.components?.some(
      (c) => c.status === 'degraded'
    );

    if (hasUnhealthyComponent) {
      status = 'unhealthy';
    } else if (hasDegradedComponent && status === 'healthy') {
      status = 'degraded';
    }

    return {
      status,
      ready: response.ready,
      phase: response.phase,
      lastCheck: new Date(),
      lastResponseTimeMs: responseTimeMs,
      consecutiveFailures: 0,
      components: response.components?.map((c) => ({
        name: c.name,
        status: c.status,
        message: c.message,
      })) || [],
      error: undefined,
    };
  }

  private processHealthError(error: unknown): Partial<HealthState> {
    const errorMessage = error instanceof Error ? error.message : String(error);
    const newFailures = this.currentState.consecutiveFailures + 1;

    return {
      status: newFailures >= MAX_CONSECUTIVE_FAILURES ? 'unhealthy' : 'degraded',
      ready: false,
      phase: 'error',
      lastCheck: new Date(),
      lastResponseTimeMs: null,
      consecutiveFailures: newFailures,
      error: errorMessage,
    };
  }

  private updateState(partialState: Partial<HealthState>): void {
    const previousStatus = this.currentState.status;
    
    this.currentState = {
      ...this.currentState,
      ...partialState,
    };

    // Notify subscribers if status changed or on every update
    const statusChanged = previousStatus !== this.currentState.status;
    if (statusChanged || partialState.lastCheck) {
      this.notifySubscribers();
    }
  }

  private notifySubscribers(): void {
    const stateCopy = { ...this.currentState };
    this.subscribers.forEach((callback) => {
      try {
        callback(stateCopy);
      } catch (error) {
        console.error('[HealthMonitor] Subscriber callback error:', error);
      }
    });
  }

  /**
   * Set the polling interval
   * @param intervalMs - New polling interval in milliseconds
   */
  setPollInterval(intervalMs: number): void {
    this.pollIntervalMs = intervalMs;
    
    // Restart polling with new interval if currently polling
    if (this.pollTimer) {
      this.stop();
      this.start();
    }
  }

  /**
   * Check if currently polling
   */
  isActive(): boolean {
    return this.pollTimer !== null;
  }
}

/**
 * Create a health monitor instance
 */
export function createHealthMonitor(
  pollIntervalMs: number = DEFAULT_POLL_INTERVAL_MS
): HealthMonitor {
  return new HealthMonitor(pollIntervalMs);
}

/**
 * Default health monitor instance
 */
export const defaultHealthMonitor = new HealthMonitor();

export default HealthMonitor;
