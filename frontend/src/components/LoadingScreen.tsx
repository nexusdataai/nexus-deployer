/**
 * Loading Screen Component
 * 
 * Displays during application startup while waiting for backend readiness.
 * Shows progress indicator, status messages, and error state with retry.
 * 
 * Feature: startup-health-check
 * Requirements: 3.1, 3.2, 3.3, 3.4, 3.5
 */
import React from 'react';

export type StartupPhase = 
  | 'connecting'
  | 'initializing'
  | 'loading_components'
  | 'ready'
  | 'error'
  | 'timeout';

export interface StartupStatus {
  phase: StartupPhase;
  message: string;
  progress?: number;
  error?: string;
  componentStatuses?: Array<{
    name: string;
    status: 'pending' | 'healthy' | 'degraded' | 'unhealthy';
  }>;
}

interface LoadingScreenProps {
  status: StartupStatus;
  onRetry?: () => void;
  className?: string;
}

const phaseMessages: Record<StartupPhase, string> = {
  connecting: 'Waiting for services...',
  initializing: 'Initializing application...',
  loading_components: 'Loading components...',
  ready: 'Ready!',
  error: 'Failed to start application',
  timeout: 'Connection timed out',
};

const phaseProgress: Record<StartupPhase, number> = {
  connecting: 20,
  initializing: 50,
  loading_components: 80,
  ready: 100,
  error: 0,
  timeout: 0,
};

// Simple SVG icons
const LoaderIcon = () => (
  <svg className="w-12 h-12 text-blue-500 animate-spin" fill="none" viewBox="0 0 24 24">
    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
  </svg>
);

const AlertIcon = () => (
  <svg className="w-12 h-12 text-red-500 animate-pulse" fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
  </svg>
);

const CheckIcon = () => (
  <svg className="w-12 h-12 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
  </svg>
);

const RefreshIcon = () => (
  <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
  </svg>
);

export const LoadingScreen: React.FC<LoadingScreenProps> = ({
  status,
  onRetry,
  className = '',
}) => {
  const isError = status.phase === 'error' || status.phase === 'timeout';
  const isReady = status.phase === 'ready';
  const progress = status.progress ?? phaseProgress[status.phase];
  const message = status.message || phaseMessages[status.phase];

  const baseClasses = 'fixed inset-0 flex flex-col items-center justify-center bg-gray-900 z-50 transition-opacity duration-300';
  const visibilityClasses = isReady ? 'opacity-0 pointer-events-none' : '';

  return (
    <div
      className={`${baseClasses} ${visibilityClasses} ${className}`}
      role="status"
      aria-live="polite"
      aria-busy={!isReady && !isError}
    >
      <div className="flex flex-col items-center max-w-md px-6 text-center">
        {/* Logo/Brand */}
        <div className="mb-8">
          <h1 className="text-2xl font-semibold text-white">
            Totogi Customer Toolkit
          </h1>
        </div>

        {/* Status Icon */}
        <div className="mb-6">
          {isError ? <AlertIcon /> : isReady ? <CheckIcon /> : <LoaderIcon />}
        </div>

        {/* Progress Bar */}
        {!isError && (
          <div className="w-full mb-4">
            <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
              <div
                className={`h-full transition-all duration-500 ease-out ${isReady ? 'bg-green-500' : 'bg-blue-500'}`}
                style={{ width: `${progress}%` }}
                role="progressbar"
                aria-valuenow={progress}
                aria-valuemin={0}
                aria-valuemax={100}
              />
            </div>
          </div>
        )}

        {/* Status Message */}
        <p className={`text-sm mb-4 ${isError ? 'text-red-400' : 'text-gray-400'}`}>
          {message}
        </p>

        {/* Error Details */}
        {isError && status.error && (
          <div className="w-full mb-4">
            <p className="text-xs text-gray-500 font-mono bg-gray-800 p-3 rounded text-left whitespace-pre-wrap max-h-32 overflow-y-auto">
              {status.error}
            </p>
          </div>
        )}

        {/* Debug Info for timeout */}
        {status.phase === 'timeout' && (
          <p className="text-xs text-gray-600 mb-2">
            The backend service at 127.0.0.1:8001 is not responding.
          </p>
        )}

        {/* Component Status List */}
        {status.componentStatuses && status.componentStatuses.length > 0 && (
          <div className="w-full mb-4">
            <div className="text-xs text-gray-500 space-y-1">
              {status.componentStatuses.map((comp) => (
                <div key={comp.name} className="flex items-center justify-between">
                  <span>{comp.name}</span>
                  <ComponentStatusBadge status={comp.status} />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Retry Button */}
        {isError && onRetry && (
          <button
            onClick={onRetry}
            className="mt-2 flex items-center px-4 py-2 text-sm font-medium text-white bg-gray-700 hover:bg-gray-600 rounded-md border border-gray-600 transition-colors"
          >
            <RefreshIcon />
            Retry
          </button>
        )}
      </div>
    </div>
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
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[status] || 'bg-gray-700 text-gray-400'}`}>
      {status}
    </span>
  );
};

export default LoadingScreen;
