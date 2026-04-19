/**
 * MFA Verification Component
 * Handles MFA code verification during login.
 */
import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../../stores/authStore';
import { AuthErrorCode, MFAMethod } from '../../types/auth';
import { authService } from '../../services/authService';

interface MFAVerifyProps {
  redirectTo?: string;
  onCancel?: () => void;
}

export const MFAVerify: React.FC<MFAVerifyProps> = ({
  redirectTo = '/',
  onCancel,
}) => {
  const navigate = useNavigate();
  const {
    isAuthenticated,
    isLoading,
    error,
    mfaSessionToken,
    mfaMethods,
    verifyMFA,
    clearError,
  } = useAuthStore();

  const [code, setCode] = useState(['', '', '', '', '', '']);
  const [retriesRemaining, setRetriesRemaining] = useState<number | null>(null);
  const [selectedMethod, setSelectedMethod] = useState<MFAMethod>('totp');
  const [codeSent, setCodeSent] = useState(false);
  const [sendingCode, setSendingCode] = useState(false);
  const inputRefs = useRef<(HTMLInputElement | null)[]>([]);

  // Redirect if already authenticated
  useEffect(() => {
    if (isAuthenticated) {
      navigate(redirectTo);
    }
  }, [isAuthenticated, navigate, redirectTo]);

  // Redirect if no MFA session
  useEffect(() => {
    if (!mfaSessionToken) {
      navigate('/login');
    }
  }, [mfaSessionToken, navigate]);

  // Set initial method based on available methods
  useEffect(() => {
    if (mfaMethods.length > 0) {
      setSelectedMethod(mfaMethods[0] as MFAMethod);
    }
  }, [mfaMethods]);

  // Focus first input on mount
  useEffect(() => {
    inputRefs.current[0]?.focus();
  }, []);

  const handleCodeChange = (index: number, value: string) => {
    // Only allow digits
    if (value && !/^\d$/.test(value)) {
      return;
    }

    const newCode = [...code];
    newCode[index] = value;
    setCode(newCode);

    // Auto-focus next input
    if (value && index < 5) {
      inputRefs.current[index + 1]?.focus();
    }

    // Auto-submit when all digits entered
    if (value && index === 5 && newCode.every((d) => d !== '')) {
      handleSubmit(newCode.join(''));
    }
  };

  const handleKeyDown = (index: number, e: React.KeyboardEvent) => {
    if (e.key === 'Backspace' && !code[index] && index > 0) {
      inputRefs.current[index - 1]?.focus();
    }
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    e.preventDefault();
    const pastedData = e.clipboardData.getData('text').replace(/\D/g, '');
    
    if (pastedData.length === 6) {
      const newCode = pastedData.split('');
      setCode(newCode);
      inputRefs.current[5]?.focus();
      handleSubmit(pastedData);
    }
  };

  const handleSubmit = async (codeString?: string) => {
    const verificationCode = codeString || code.join('');
    
    if (verificationCode.length !== 6) {
      return;
    }

    clearError();
    const response = await verifyMFA(verificationCode);

    if (response.success) {
      navigate(redirectTo);
    } else {
      // Clear code on failure
      setCode(['', '', '', '', '', '']);
      inputRefs.current[0]?.focus();

      if (response.retries_remaining !== undefined) {
        setRetriesRemaining(response.retries_remaining);
      }

      if (response.error_code === AuthErrorCode.MFA_RETRIES_EXHAUSTED) {
        // Redirect to login after exhausting retries
        setTimeout(() => {
          navigate('/login');
        }, 3000);
      }
    }
  };

  const handleSendCode = async () => {
    if (!mfaSessionToken || selectedMethod === 'totp') {
      return;
    }

    setSendingCode(true);
    try {
      const response = await authService.sendMFACode({
        mfa_session_token: mfaSessionToken,
        method: selectedMethod,
      });

      if (response.success) {
        setCodeSent(true);
      }
    } finally {
      setSendingCode(false);
    }
  };

  const handleCancel = () => {
    if (onCancel) {
      onCancel();
    } else {
      navigate('/login');
    }
  };

  const getMethodLabel = (method: string): string => {
    switch (method) {
      case 'totp':
        return 'Authenticator App';
      case 'sms':
        return 'SMS';
      case 'email':
        return 'Email';
      default:
        return method;
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-md w-full space-y-8">
        {/* Header */}
        <div>
          <h2 className="mt-6 text-center text-3xl font-extrabold text-gray-900">
            Two-Factor Authentication
          </h2>
          <p className="mt-2 text-center text-sm text-gray-600">
            {selectedMethod === 'totp'
              ? 'Enter the code from your authenticator app'
              : `Enter the code sent to your ${selectedMethod}`}
          </p>
        </div>

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
                {retriesRemaining !== null && retriesRemaining > 0 && (
                  <p className="text-sm text-red-700 mt-1">
                    {retriesRemaining} attempt{retriesRemaining !== 1 ? 's' : ''} remaining
                  </p>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Method selector (if multiple methods available) */}
        {mfaMethods.length > 1 && (
          <div className="flex justify-center space-x-4">
            {mfaMethods.map((method) => (
              <button
                key={method}
                type="button"
                onClick={() => {
                  setSelectedMethod(method as MFAMethod);
                  setCodeSent(false);
                  setCode(['', '', '', '', '', '']);
                }}
                className={`px-4 py-2 text-sm font-medium rounded-md ${
                  selectedMethod === method
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
                }`}
              >
                {getMethodLabel(method)}
              </button>
            ))}
          </div>
        )}

        {/* Send code button for SMS/Email */}
        {selectedMethod !== 'totp' && !codeSent && (
          <div className="text-center">
            <button
              type="button"
              onClick={handleSendCode}
              disabled={sendingCode}
              className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400"
            >
              {sendingCode ? (
                <>
                  <svg
                    className="animate-spin -ml-1 mr-2 h-4 w-4 text-white"
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
                  Sending...
                </>
              ) : (
                `Send code via ${getMethodLabel(selectedMethod)}`
              )}
            </button>
          </div>
        )}

        {/* Code input */}
        {(selectedMethod === 'totp' || codeSent) && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSubmit();
            }}
            className="mt-8 space-y-6"
          >
            <div className="flex justify-center space-x-2">
              {code.map((digit, index) => (
                <input
                  key={index}
                  ref={(el) => (inputRefs.current[index] = el)}
                  type="text"
                  inputMode="numeric"
                  maxLength={1}
                  value={digit}
                  onChange={(e) => handleCodeChange(index, e.target.value)}
                  onKeyDown={(e) => handleKeyDown(index, e)}
                  onPaste={index === 0 ? handlePaste : undefined}
                  disabled={isLoading}
                  className="w-12 h-14 text-center text-2xl font-bold border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:bg-gray-100"
                  aria-label={`Digit ${index + 1}`}
                />
              ))}
            </div>

            <div className="flex space-x-4">
              <button
                type="button"
                onClick={handleCancel}
                disabled={isLoading}
                className="flex-1 py-2 px-4 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:bg-gray-100"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isLoading || code.some((d) => d === '')}
                className="flex-1 py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:bg-gray-400 disabled:cursor-not-allowed"
              >
                {isLoading ? (
                  <span className="flex items-center justify-center">
                    <svg
                      className="animate-spin -ml-1 mr-2 h-4 w-4 text-white"
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
                    Verifying...
                  </span>
                ) : (
                  'Verify'
                )}
              </button>
            </div>
          </form>
        )}

        {/* Resend code option */}
        {selectedMethod !== 'totp' && codeSent && (
          <div className="text-center">
            <button
              type="button"
              onClick={handleSendCode}
              disabled={sendingCode}
              className="text-sm text-blue-600 hover:text-blue-500"
            >
              Didn't receive the code? Send again
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default MFAVerify;
