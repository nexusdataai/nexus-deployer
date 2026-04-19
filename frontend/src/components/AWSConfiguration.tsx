/**
 * Enhanced AWS Configuration Component with Multiple Auth Methods
 */
import React, { useState, useEffect } from 'react';
import { useWizard } from '../context/WizardContext';
import { WizardStep } from '../types/wizard';
import { AWSRegion, AWSAuthMethod } from '../types/aws';
import { awsApi } from '../services/api';

const AWSConfiguration: React.FC = () => {
  const { state, setAWSConfig, setStep } = useWizard();
  const [roleArn, setRoleArn] = useState('');
  const [region, setRegion] = useState('');
  const [regions, setRegions] = useState<AWSRegion[]>([]);
  const [validating, setValidating] = useState(false);
  const [validated, setValidated] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [troubleshooting, setTroubleshooting] = useState<string[]>([]);

  useEffect(() => {
    loadRegions();
  }, []);

  const loadRegions = async () => {
    try {
      const data = await awsApi.getRegions();
      setRegions(data);
      if (data.length > 0) {
        setRegion(data[0].code);
      }
    } catch (err) {
      console.error('Error loading regions:', err);
    }
  };

  const validateArnFormat = (arn: string): boolean => {
    const arnPattern = /^arn:aws:iam::\d{12}:role\/[\w+=,.@-]+$/;
    return arnPattern.test(arn);
  };

  const handleTestCredentials = async () => {
    setError(null);
    setTroubleshooting([]);
    setValidated(false);

    if (!roleArn) {
      setError('Please enter a Role ARN');
      return;
    }

    if (!validateArnFormat(roleArn)) {
      setError('Invalid Role ARN format');
      setTroubleshooting([
        'Role ARN must match pattern: arn:aws:iam::<account-id>:role/<role-name>',
        'Example: arn:aws:iam::123456789012:role/MyDeploymentRole',
      ]);
      return;
    }

    if (!region) {
      setError('Please select a region');
      return;
    }

    try {
      setValidating(true);
      const response = await awsApi.validateCredentials({ role_arn: roleArn, region });

      if (response.valid) {
        setValidated(true);
        setAWSConfig({
          auth_method: AWSAuthMethod.ROLE_ARN,
          role_arn: roleArn,
          region,
          account_id: response.account_id,
        });
      } else {
        setError(response.error || 'Failed to validate credentials');
        setTroubleshooting(response.troubleshooting || []);
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to validate credentials');
      setTroubleshooting([
        'Check that the backend server is running',
        'Verify network connectivity',
        'Ensure AWS credentials are configured on the backend',
      ]);
    } finally {
      setValidating(false);
    }
  };

  const handleContinue = () => {
    if (validated) {
      setStep(WizardStep.PERMISSION_VERIFICATION);
    }
  };

  return (
    <div className="max-w-4xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">AWS Configuration</h1>
        <p className="text-gray-600">
          Configure AWS credentials and region for deploying {state.selectedCapability?.name} to{' '}
          {state.selectedEnvironment}
        </p>
      </div>

      <div className="bg-white rounded-lg shadow-md p-8 mb-8">
        {/* Role ARN Input */}
        <div className="mb-6">
          <label htmlFor="roleArn" className="block text-sm font-medium text-gray-700 mb-2">
            AWS Role ARN <span className="text-red-500">*</span>
          </label>
          <input
            type="text"
            id="roleArn"
            value={roleArn}
            onChange={(e) => {
              setRoleArn(e.target.value);
              setValidated(false);
              setError(null);
            }}
            placeholder="arn:aws:iam::123456789012:role/MyDeploymentRole"
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
          <p className="mt-1 text-sm text-gray-500">
            IAM Role ARN that the installer will assume for deployment
          </p>
        </div>

        {/* Region Selection */}
        <div className="mb-6">
          <label htmlFor="region" className="block text-sm font-medium text-gray-700 mb-2">
            AWS Region <span className="text-red-500">*</span>
          </label>
          <select
            id="region"
            value={region}
            onChange={(e) => {
              setRegion(e.target.value);
              setValidated(false);
            }}
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          >
            {regions.map((r) => (
              <option key={r.code} value={r.code}>
                {r.name} ({r.code})
              </option>
            ))}
          </select>
          <p className="mt-1 text-sm text-gray-500">
            AWS region where resources will be deployed
          </p>
        </div>

        {/* Test Credentials Button */}
        <div className="mb-6">
          <button
            onClick={handleTestCredentials}
            disabled={validating || !roleArn || !region}
            className={`w-full px-6 py-3 rounded-lg font-medium ${
              validating || !roleArn || !region
                ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                : 'bg-blue-600 text-white hover:bg-blue-700'
            }`}
          >
            {validating ? (
              <span className="flex items-center justify-center">
                <svg
                  className="animate-spin -ml-1 mr-3 h-5 w-5 text-white"
                  xmlns="http://www.w3.org/2000/svg"
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
                  ></circle>
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  ></path>
                </svg>
                Testing Credentials...
              </span>
            ) : (
              'Test Credentials'
            )}
          </button>
        </div>

        {/* Validation Success */}
        {validated && (
          <div className="bg-green-50 border border-green-200 rounded-lg p-4 mb-6">
            <div className="flex items-start">
              <svg
                className="w-5 h-5 text-green-600 mr-3 mt-0.5"
                fill="currentColor"
                viewBox="0 0 20 20"
              >
                <path
                  fillRule="evenodd"
                  d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                  clipRule="evenodd"
                />
              </svg>
              <div>
                <p className="font-medium text-green-800">Credentials Validated Successfully</p>
                <p className="text-sm text-green-700 mt-1">
                  Successfully assumed role. Account ID: {state.awsConfig?.account_id}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Validation Error */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
            <div className="flex items-start">
              <svg
                className="w-5 h-5 text-red-600 mr-3 mt-0.5 flex-shrink-0"
                fill="currentColor"
                viewBox="0 0 20 20"
              >
                <path
                  fillRule="evenodd"
                  d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
                  clipRule="evenodd"
                />
              </svg>
              <div className="flex-1">
                <p className="font-medium text-red-800">Validation Failed</p>
                <p className="text-sm text-red-700 mt-1">{error}</p>
                {troubleshooting.length > 0 && (
                  <div className="mt-3">
                    <p className="text-sm font-medium text-red-800 mb-1">Troubleshooting:</p>
                    <ul className="list-disc list-inside space-y-1">
                      {troubleshooting.map((tip, index) => (
                        <li key={index} className="text-sm text-red-700">
                          {tip}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Info Box */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-8">
        <div className="flex items-start">
          <svg
            className="w-5 h-5 text-blue-600 mr-3 mt-0.5 flex-shrink-0"
            fill="currentColor"
            viewBox="0 0 20 20"
          >
            <path
              fillRule="evenodd"
              d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
              clipRule="evenodd"
            />
          </svg>
          <div className="text-sm text-blue-800">
            <p className="font-medium mb-1">About IAM Roles</p>
            <p>
              The installer needs an IAM role with permissions to create AWS resources. The role's
              trust policy must allow your AWS account to assume it. We'll verify permissions in the
              next step.
            </p>
          </div>
        </div>
      </div>

      {/* Action Buttons */}
      <div className="flex justify-between">
        <button
          onClick={() => setStep(WizardStep.UNIFIED_ENVIRONMENT_CONFIG)}
          className="px-6 py-3 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50"
        >
          Back
        </button>
        <button
          onClick={handleContinue}
          disabled={!validated}
          className={`px-6 py-3 rounded-lg font-medium ${
            validated
              ? 'bg-blue-600 text-white hover:bg-blue-700'
              : 'bg-gray-300 text-gray-500 cursor-not-allowed'
          }`}
        >
          Continue
        </button>
      </div>
    </div>
  );
};

export default AWSConfiguration;
