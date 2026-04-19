/**
 * SSO Login Component
 * Displays SSO provider buttons and handles SSO callback.
 */
import React, { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuthStore } from '../../stores/authStore';
import { SSOProvider } from '../../types/auth';

interface SSOLoginProps {
  redirectTo?: string;
  showLocalLogin?: boolean;
  onLocalLoginClick?: () => void;
}

export const SSOLogin: React.FC<SSOLoginProps> = ({
  redirectTo = '/',
  showLocalLogin = true,
  onLocalLoginClick,
}) => {
  const navigate = useNavigate();
  const {
    isAuthenticated,
    isLoading,
    error,
    ssoEnabled,
    ssoProviders,
    loadSSOConfig,
    initiateSSOLogin,
    clearError,
  } = useAuthStore();

  // Load SSO config on mount
  useEffect(() => {
    loadSSOConfig();
  }, [loadSSOConfig]);

  // Redirect if already authenticated
  useEffect(() => {
    if (isAuthenticated) {
      navigate(redirectTo);
    }
  }, [isAuthenticated, navigate, redirectTo]);

  const handleSSOLogin = (providerId: string) => {
    clearError();
    initiateSSOLogin(providerId);
  };

  const handleLocalLogin = () => {
    if (onLocalLoginClick) {
      onLocalLoginClick();
    } else {
      navigate('/login');
    }
  };

  const getProviderIcon = (provider: SSOProvider): React.ReactNode => {
    if (provider.icon_url) {
      return (
        <img
          src={provider.icon_url}
          alt=""
          className="h-5 w-5 mr-3"
        />
      );
    }

    // Default icons based on provider type
    switch (provider.type) {
      case 'saml':
        return (
          <svg className="h-5 w-5 mr-3 text-gray-500" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z" clipRule="evenodd" />
          </svg>
        );
      case 'oauth':
      case 'oidc':
        return (
          <svg className="h-5 w-5 mr-3 text-gray-500" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-6-3a2 2 0 11-4 0 2 2 0 014 0zm-2 4a5 5 0 00-4.546 2.916A5.986 5.986 0 0010 16a5.986 5.986 0 004.546-2.084A5 5 0 0010 11z" clipRule="evenodd" />
          </svg>
        );
      default:
        return null;
    }
  };

  if (!ssoEnabled || ssoProviders.length === 0) {
    return null;
  }

  return (
    <div className="space-y-4">
      {/* Error message */}
      {error && (
        <div className="rounded-md bg-red-50 p-4">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg
                className="h-5 w-5 text-red-400"
                viewBox="0 0 20 20"
                fill="currentColor"
              >
                <path
                  fillRule="evenodd"
                  d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
                  clipRule="evenodd"
                />
              </svg>
            </div>
            <div className="ml-3">
              <p className="text-sm font-medium text-red-800">{error}</p>
              {showLocalLogin && (
                <p className="text-sm text-red-700 mt-1">
                  You can also{' '}
                  <button
                    type="button"
                    onClick={handleLocalLogin}
                    className="underline hover:text-red-900"
                  >
                    sign in with username and password
                  </button>
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* SSO provider buttons */}
      <div className="space-y-3">
        {ssoProviders.map((provider) => (
          <button
            key={provider.id}
            type="button"
            onClick={() => handleSSOLogin(provider.id)}
            disabled={isLoading}
            className="w-full inline-flex items-center justify-center py-3 px-4 border border-gray-300 rounded-md shadow-sm bg-white text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:bg-gray-100 disabled:cursor-not-allowed transition-colors"
          >
            {isLoading ? (
              <svg
                className="animate-spin h-5 w-5 mr-3 text-gray-500"
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
            ) : (
              getProviderIcon(provider)
            )}
            Continue with {provider.name}
          </button>
        ))}
      </div>

      {/* Divider and local login option */}
      {showLocalLogin && (
        <>
          <div className="relative">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-gray-300" />
            </div>
            <div className="relative flex justify-center text-sm">
              <span className="px-2 bg-white text-gray-500">Or</span>
            </div>
          </div>

          <button
            type="button"
            onClick={handleLocalLogin}
            className="w-full inline-flex items-center justify-center py-2 px-4 text-sm font-medium text-blue-600 hover:text-blue-500"
          >
            Sign in with username and password
          </button>
        </>
      )}
    </div>
  );
};

/**
 * SSO Callback Handler Component
 * Handles the OAuth/OIDC callback after SSO authentication.
 */
export const SSOCallback: React.FC<{ redirectTo?: string }> = ({
  redirectTo = '/',
}) => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { handleSSOCallback, error } = useAuthStore();
  const [processing, setProcessing] = useState(true);

  useEffect(() => {
    const processCallback = async () => {
      const code = searchParams.get('code');
      const state = searchParams.get('state');
      const errorParam = searchParams.get('error');
      const errorDescription = searchParams.get('error_description');

      if (errorParam) {
        // SSO provider returned an error
        navigate('/login', {
          state: { error: errorDescription || errorParam },
        });
        return;
      }

      if (!code || !state) {
        navigate('/login', {
          state: { error: 'Invalid SSO callback parameters' },
        });
        return;
      }

      const success = await handleSSOCallback(code, state);
      setProcessing(false);

      if (success) {
        navigate(redirectTo);
      } else {
        // Stay on callback page to show error with fallback option
      }
    };

    processCallback();
  }, [searchParams, handleSSOCallback, navigate, redirectTo]);

  if (processing) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <svg
            className="animate-spin h-12 w-12 text-blue-600 mx-auto"
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
          <p className="mt-4 text-gray-600">Completing sign in...</p>
        </div>
      </div>
    );
  }

  // Show error with fallback option
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4">
      <div className="max-w-md w-full space-y-8">
        <div className="rounded-md bg-red-50 p-4">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg
                className="h-5 w-5 text-red-400"
                viewBox="0 0 20 20"
                fill="currentColor"
              >
                <path
                  fillRule="evenodd"
                  d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
                  clipRule="evenodd"
                />
              </svg>
            </div>
            <div className="ml-3">
              <h3 className="text-sm font-medium text-red-800">
                SSO Authentication Failed
              </h3>
              <p className="text-sm text-red-700 mt-1">
                {error || 'An error occurred during SSO authentication.'}
              </p>
            </div>
          </div>
        </div>

        <div className="text-center">
          <p className="text-gray-600 mb-4">
            You can try again or use local authentication.
          </p>
          <div className="space-y-3">
            <button
              type="button"
              onClick={() => navigate('/login')}
              className="w-full py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700"
            >
              Go to Login
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default SSOLogin;
