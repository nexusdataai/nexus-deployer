/**
 * UserMenu Component
 * Displays user avatar, username, and role badge with dropdown functionality.
 * 
 * Feature: user-menu
 * Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3
 */
import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../stores/authStore';
import { authService } from '../services/authService';
import { UserRole } from '../types/auth';
import { UserAvatar } from './UserAvatar';

interface UserMenuProps {
  className?: string;
}

// Role badge styling based on role
const roleBadgeStyles: Record<UserRole, string> = {
  Administrator: 'bg-purple-100 text-purple-800',
  Operator: 'bg-blue-100 text-blue-800',
  Viewer: 'bg-gray-100 text-gray-800',
};

export const UserMenu: React.FC<UserMenuProps> = ({ className = '' }) => {
  const navigate = useNavigate();
  const { user, logout, isLoading } = useAuthStore();
  const [isOpen, setIsOpen] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const firstMenuItemRef = useRef<HTMLButtonElement>(null);

  const displayName = user?.username || 'User';
  const displayRole = user?.roles?.[0] || 'Viewer';
  const displayEmail = user?.email || '';
  const mfaEnabled = user?.mfa_enabled || false;

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen]);

  // Handle Escape key to close dropdown
  useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && isOpen) {
        setIsOpen(false);
        buttonRef.current?.focus();
      }
    };

    if (isOpen) {
      document.addEventListener('keydown', handleEscape);
    }

    return () => {
      document.removeEventListener('keydown', handleEscape);
    };
  }, [isOpen]);

  // Focus first menu item when dropdown opens
  useEffect(() => {
    if (isOpen && firstMenuItemRef.current) {
      firstMenuItemRef.current.focus();
    }
  }, [isOpen]);

  // Focus trap - cycle through menu items with Tab
  const handleFocusTrap = useCallback((event: KeyboardEvent) => {
    if (!isOpen || event.key !== 'Tab') return;
    
    const focusableElements = menuRef.current?.querySelectorAll(
      'button:not([disabled]), [tabindex="0"]'
    );
    
    if (!focusableElements || focusableElements.length === 0) return;
    
    const firstElement = focusableElements[0] as HTMLElement;
    const lastElement = focusableElements[focusableElements.length - 1] as HTMLElement;
    
    if (event.shiftKey) {
      // Shift+Tab: if on first element, go to last
      if (document.activeElement === firstElement) {
        event.preventDefault();
        lastElement.focus();
      }
    } else {
      // Tab: if on last element, go to first
      if (document.activeElement === lastElement) {
        event.preventDefault();
        firstElement.focus();
      }
    }
  }, [isOpen]);

  useEffect(() => {
    if (isOpen) {
      document.addEventListener('keydown', handleFocusTrap);
    }
    return () => {
      document.removeEventListener('keydown', handleFocusTrap);
    };
  }, [isOpen, handleFocusTrap]);

  const toggleDropdown = useCallback(() => {
    setIsOpen(prev => !prev);
  }, []);

  const handleLogout = useCallback(async () => {
    setIsLoggingOut(true);
    try {
      await logout();
      navigate('/login');
    } catch (error) {
      // Even on error, clear local state and redirect
      authService.clearAuth();
      navigate('/login');
    } finally {
      setIsLoggingOut(false);
      setIsOpen(false);
    }
  }, [logout, navigate]);

  const handleChangePassword = useCallback(() => {
    setIsOpen(false);
    navigate('/change-password');
  }, [navigate]);

  // Handle keyboard navigation within dropdown
  const handleKeyDown = useCallback((event: React.KeyboardEvent, action: () => void) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      action();
    }
  }, []);

  return (
    <div ref={menuRef} className={`relative ${className}`}>
      {/* Menu Trigger Button */}
      <button
        ref={buttonRef}
        id="user-menu-button"
        onClick={toggleDropdown}
        className="flex items-center space-x-2 p-2 rounded-lg hover:bg-gray-100 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
        aria-haspopup="true"
        aria-expanded={isOpen}
        aria-label={`User menu for ${displayName}`}
      >
        <UserAvatar username={displayName} size="sm" />
        {/* Username - hidden on mobile */}
        <span className="hidden md:block text-sm font-medium text-gray-700">
          {displayName}
        </span>
        {/* Role badge - hidden on mobile */}
        <span
          className={`hidden md:inline-flex px-2 py-0.5 text-xs font-medium rounded-full ${roleBadgeStyles[displayRole as UserRole] || roleBadgeStyles.Viewer}`}
        >
          {displayRole}
        </span>
        {/* Dropdown arrow */}
        <svg
          className={`h-4 w-4 text-gray-500 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Dropdown Panel */}
      {isOpen && (
        <div
          role="menu"
          aria-labelledby="user-menu-button"
          className="absolute right-0 mt-2 w-64 md:w-72 bg-white rounded-lg shadow-lg border border-gray-200 py-2 z-50"
        >
          {/* User Info Section */}
          <div className="px-4 py-3 border-b border-gray-100">
            <div className="flex items-center space-x-3">
              <UserAvatar username={displayName} size="md" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-gray-900 truncate">
                  {displayName}
                </p>
                {displayEmail && (
                  <p className="text-xs text-gray-500 truncate">
                    {displayEmail}
                  </p>
                )}
                <div className="flex items-center mt-1 space-x-2">
                  <span
                    className={`inline-flex px-2 py-0.5 text-xs font-medium rounded-full ${roleBadgeStyles[displayRole as UserRole] || roleBadgeStyles.Viewer}`}
                  >
                    {displayRole}
                  </span>
                  {mfaEnabled && (
                    <span className="inline-flex items-center px-2 py-0.5 text-xs font-medium rounded-full bg-green-100 text-green-800">
                      <svg className="w-3 h-3 mr-1" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M2.166 4.999A11.954 11.954 0 0010 1.944 11.954 11.954 0 0017.834 5c.11.65.166 1.32.166 2.001 0 5.225-3.34 9.67-8 11.317C5.34 16.67 2 12.225 2 7c0-.682.057-1.35.166-2.001zm11.541 3.708a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                      </svg>
                      MFA
                    </span>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Menu Items */}
          <div className="py-1">
            {/* Change Password */}
            <button
              ref={firstMenuItemRef}
              role="menuitem"
              tabIndex={0}
              onClick={handleChangePassword}
              onKeyDown={(e) => handleKeyDown(e, handleChangePassword)}
              className="w-full flex items-center px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 focus:bg-gray-100 focus:outline-none"
            >
              <svg className="w-5 h-5 mr-3 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
              </svg>
              Change Password
            </button>

            {/* Divider */}
            <div className="border-t border-gray-100 my-1" />

            {/* Logout */}
            <button
              role="menuitem"
              tabIndex={0}
              onClick={handleLogout}
              onKeyDown={(e) => handleKeyDown(e, handleLogout)}
              disabled={isLoggingOut || isLoading}
              className="w-full flex items-center px-4 py-2 text-sm text-red-600 hover:bg-red-50 focus:bg-red-50 focus:outline-none disabled:opacity-50"
            >
              {isLoggingOut ? (
                <svg className="animate-spin w-5 h-5 mr-3 text-red-400" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
              ) : (
                <svg className="w-5 h-5 mr-3 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                </svg>
              )}
              {isLoggingOut ? 'Logging out...' : 'Logout'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default UserMenu;
