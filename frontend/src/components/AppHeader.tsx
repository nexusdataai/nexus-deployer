/**
 * AppHeader Component
 * Top-level header component that displays application title and user menu.
 * 
 * Feature: user-menu
 * Requirements: 1.1, 1.2
 */
import React from 'react';
import { UserMenu } from './UserMenu';

interface AppHeaderProps {
  title?: string;
  showProgress?: boolean;
  currentStep?: number;
  totalSteps?: number;
  capabilityName?: string;
  children?: React.ReactNode;
}

export const AppHeader: React.FC<AppHeaderProps> = ({
  title = 'Totogi Customer Toolkit',
  showProgress = false,
  currentStep,
  totalSteps,
  capabilityName,
  children,
}) => {
  return (
    <header className="bg-white border-b border-gray-200 sticky top-0 z-40">
      <div className="max-w-7xl mx-auto px-4">
        {/* Main Header Row */}
        <div className="flex items-center justify-between h-16">
          {/* Left: Logo/Title */}
          <div className="flex items-center space-x-4">
            {/* Logo */}
            <div className="flex-shrink-0">
              <svg
                className="h-8 w-8 text-blue-600"
                fill="currentColor"
                viewBox="0 0 24 24"
              >
                <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
              </svg>
            </div>
            {/* Title */}
            <div className="hidden sm:block">
              <h1 className="text-lg font-semibold text-gray-900">{title}</h1>
            </div>
          </div>

          {/* Center: Optional children (e.g., navigation) */}
          {children && (
            <div className="hidden md:flex items-center space-x-4">
              {children}
            </div>
          )}

          {/* Right: User Menu */}
          <div className="flex items-center">
            <UserMenu />
          </div>
        </div>

        {/* Progress Bar Row (optional) */}
        {showProgress && currentStep !== undefined && totalSteps !== undefined && (
          <div className="pb-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-gray-700">
                Step {currentStep} of {totalSteps}
              </span>
              {capabilityName && (
                <span className="text-sm text-gray-500">
                  {capabilityName}
                </span>
              )}
            </div>
            <div className="w-full bg-gray-200 rounded-full h-2">
              <div
                className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                style={{ width: `${(currentStep / totalSteps) * 100}%` }}
              />
            </div>
          </div>
        )}
      </div>
    </header>
  );
};

export default AppHeader;
