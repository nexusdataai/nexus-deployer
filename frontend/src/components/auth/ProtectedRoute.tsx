/**
 * Protected Route Component
 * Wraps routes that require authentication and optionally specific roles.
 */
import React, { useEffect, useState, useRef } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '../../stores/authStore';
import { UserRole, hasAnyRole } from '../../types/auth';

interface ProtectedRouteProps {
  children: React.ReactNode;
  requiredRoles?: UserRole[];
  redirectTo?: string;
  fallback?: React.ReactNode;
  allowPasswordChange?: boolean; // Allow access even if password change required
}

export const ProtectedRoute: React.FC<ProtectedRouteProps> = ({
  children,
  requiredRoles,
  redirectTo = '/login',
  fallback,
  allowPasswordChange = false,
}) => {
  const location = useLocation();
  const { isAuthenticated, isLoading, user, checkAuth } = useAuthStore();
  const [checking, setChecking] = useState(true);
  const hasChecked = useRef(false);

  // Check authentication on mount (only once)
  useEffect(() => {
    if (hasChecked.current) return;
    hasChecked.current = true;
    
    const verify = async () => {
      await checkAuth();
      setChecking(false);
    };
    verify();
  }, []); // Empty dependency array - run only once

  // Show loading state while checking auth
  if (checking || isLoading) {
    return (
      fallback || (
        <div className="min-h-screen flex items-center justify-center bg-gray-50">
          <div className="text-center">
            <svg
              className="animate-spin h-10 w-10 text-blue-600 mx-auto"
              fill="none"
              viewBox="0 0 24 24"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
              />
            </svg>
            <p className="mt-4 text-gray-600">Loading...</p>
          </div>
        </div>
      )
    );
  }

  // Redirect to login if not authenticated
  if (!isAuthenticated) {
    return (
      <Navigate
        to={redirectTo}
        state={{ from: location.pathname }}
        replace
      />
    );
  }

  // Check if password change is required (unless this route allows it)
  if (!allowPasswordChange && user?.require_password_change) {
    return (
      <Navigate
        to="/change-password"
        state={{ from: location.pathname, forced: true }}
        replace
      />
    );
  }

  // Check role requirements
  if (requiredRoles && requiredRoles.length > 0) {
    if (!hasAnyRole(user, requiredRoles)) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4">
          <div className="max-w-md w-full space-y-8 text-center">
            <div>
              <svg
                className="mx-auto h-16 w-16 text-red-400"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                />
              </svg>
              <h2 className="mt-6 text-2xl font-bold text-gray-900">
                Access Denied
              </h2>
              <p className="mt-2 text-gray-600">
                You don't have permission to access this page.
              </p>
              <p className="mt-1 text-sm text-gray-500">
                Required role: {requiredRoles.join(' or ')}
              </p>
            </div>
            <div>
              <button
                type="button"
                onClick={() => window.history.back()}
                className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700"
              >
                Go Back
              </button>
            </div>
          </div>
        </div>
      );
    }
  }

  return <>{children}</>;
};

/**
 * Admin-only route wrapper
 */
export const AdminRoute: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  return (
    <ProtectedRoute requiredRoles={['Administrator']}>
      {children}
    </ProtectedRoute>
  );
};

/**
 * Operator route wrapper (allows Admin and Operator)
 */
export const OperatorRoute: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  return (
    <ProtectedRoute requiredRoles={['Administrator', 'Operator']}>
      {children}
    </ProtectedRoute>
  );
};

export default ProtectedRoute;
