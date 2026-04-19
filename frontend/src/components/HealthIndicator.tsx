/**
 * Health Status Indicator Component
 * 
 * Displays backend health status in the header with tooltip details.
 * Shows warning banner when in degraded mode.
 * 
 * Feature: startup-health-check
 * Requirements: 6.3, 10.1, 10.5, 10.6
 */
import React, { useEffect, useState, useRef } from 'react';
import { HealthMonitor, HealthState, HealthStatus, defaultHealthMonitor } from '../services/health-monitor';

interface HealthIndicatorProps {
  monitor?: HealthMonitor;
  showBanner?: boolean;
  onDiagnosticsClick?: () => void;
  className?: string;
}

const statusConfig: Record<HealthStatus, {
  color: string;
  bgColor: string;
  label: string;
  iconPath: string;
}> = {
  healthy: {
    color: 'text-green-500',
    bgColor: 'bg-green-500/10',
    label: 'All systems operational',
    iconPath: 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z',
  },
  degraded: {
    color: 'text-yellow-500',
    bgColor: 'bg-yellow-500/10',
    label: 'Some services degraded',
    iconPath: 'M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z',
  },
  unhealthy: {
    color: 'text-red-500',
    bgColor: 'bg-red-500/10',
    label: 'Services unavailable',
    iconPath: 'M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z',
  },
  unknown: {
    color: 'text-gray-400',
    bgColor: 'bg-gray-500/10',
    label: 'Checking status...',
    iconPath: 'M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
  },
};

export const HealthIndicator: React.FC<HealthIndicatorProps> = ({
  monitor = defaultHealthMonitor,
  showBanner = true,
  onDiagnosticsClick,
  className = '',
}) => {
  const [healthState, setHealthState] = useState<HealthState>(monitor.getState());
  const [showTooltip, setShowTooltip] = useState(false);
  const tooltipRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const unsubscribe = monitor.subscribe(setHealthState);
    
    if (!monitor.isActive()) {
      monitor.start();
    }

    return () => {
      unsubscribe();
    };
  }, [monitor]);

  // Close tooltip when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (tooltipRef.current && !tooltipRef.current.contains(event.target as Node)) {
        setShowTooltip(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const config = statusConfig[healthState.status];

  const formatResponseTime = (ms: number | null): string => {
    if (ms === null) return 'N/A';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  const formatLastCheck = (date: Date | null): string => {
    if (!date) return 'Never';
    const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.floor(seconds / 60);
    return `${minutes}m ago`;
  };

  return (
    <>
      {/* Degraded Mode Banner */}
      {showBanner && healthState.status === 'degraded' && (
        <div className="fixed top-0 left-0 right-0 z-50 bg-yellow-500/90 text-yellow-950 px-4 py-2 text-sm text-center">
          <svg className="inline-block w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={statusConfig.degraded.iconPath} />
          </svg>
          Some services are running in degraded mode. Some features may be limited.
          {onDiagnosticsClick && (
            <button onClick={onDiagnosticsClick} className="ml-2 underline hover:no-underline">
              View details
            </button>
          )}
        </div>
      )}

      {/* Unhealthy Banner */}
      {showBanner && healthState.status === 'unhealthy' && (
        <div className="fixed top-0 left-0 right-0 z-50 bg-red-500/90 text-white px-4 py-2 text-sm text-center">
          <svg className="inline-block w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={statusConfig.unhealthy.iconPath} />
          </svg>
          Backend services are unavailable. Please check your connection.
          {onDiagnosticsClick && (
            <button onClick={onDiagnosticsClick} className="ml-2 underline hover:no-underline">
              View diagnostics
            </button>
          )}
        </div>
      )}

      {/* Health Status Icon with Tooltip */}
      <div className={`relative ${className}`} ref={tooltipRef}>
        <button
          onClick={() => {
            setShowTooltip(!showTooltip);
            if (onDiagnosticsClick && !showTooltip) {
              // Optional: trigger diagnostics on click
            }
          }}
          className={`flex items-center gap-2 px-2 py-1 rounded-md transition-colors hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 ${config.bgColor}`}
          aria-label={`Health status: ${config.label}`}
        >
          <svg className={`w-4 h-4 ${config.color}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={config.iconPath} />
          </svg>
          {/* Activity pulse indicator */}
          <span className={`w-2 h-2 rounded-full ${config.color.replace('text-', 'bg-')} animate-pulse`} />
        </button>

        {/* Tooltip */}
        {showTooltip && (
          <div className="absolute right-0 top-full mt-2 w-64 bg-gray-800 border border-gray-700 rounded-lg shadow-lg p-3 z-50">
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <svg className={`w-4 h-4 ${config.color}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={config.iconPath} />
                </svg>
                <span className="font-medium text-white">{config.label}</span>
              </div>
              
              <div className="text-xs text-gray-400 space-y-1">
                <div className="flex justify-between">
                  <span>Phase:</span>
                  <span className="font-mono text-gray-300">{healthState.phase}</span>
                </div>
                <div className="flex justify-between">
                  <span>Response time:</span>
                  <span className="font-mono text-gray-300">
                    {formatResponseTime(healthState.lastResponseTimeMs)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span>Last check:</span>
                  <span className="text-gray-300">{formatLastCheck(healthState.lastCheck)}</span>
                </div>
                {healthState.consecutiveFailures > 0 && (
                  <div className="flex justify-between text-yellow-400">
                    <span>Failed checks:</span>
                    <span>{healthState.consecutiveFailures}</span>
                  </div>
                )}
              </div>

              {/* Component Status */}
              {healthState.components.length > 0 && (
                <div className="border-t border-gray-700 pt-2 mt-2">
                  <div className="text-xs font-medium text-gray-300 mb-1">Components</div>
                  <div className="space-y-1">
                    {healthState.components.map((comp) => (
                      <div key={comp.name} className="flex items-center justify-between text-xs">
                        <span className="text-gray-400">{comp.name}</span>
                        <ComponentStatusBadge status={comp.status} />
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Error Message */}
              {healthState.error && (
                <div className="border-t border-gray-700 pt-2 mt-2 text-xs text-red-400">
                  {healthState.error}
                </div>
              )}

              {onDiagnosticsClick && (
                <button
                  onClick={onDiagnosticsClick}
                  className="w-full mt-2 text-xs text-blue-400 hover:text-blue-300 text-center"
                >
                  View detailed diagnostics →
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </>
  );
};

const ComponentStatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const colors: Record<string, string> = {
    pending: 'bg-yellow-500/20 text-yellow-400',
    healthy: 'bg-green-500/20 text-green-400',
    degraded: 'bg-orange-500/20 text-orange-400',
    unhealthy: 'bg-red-500/20 text-red-400',
  };

  return (
    <span className={`px-1.5 py-0.5 rounded text-xs ${colors[status] || 'bg-gray-700 text-gray-400'}`}>
      {status}
    </span>
  );
};

export default HealthIndicator;
