/**
 * Results Component
 * Displays final deployment results and next steps
 */
import React from 'react';
import { useWizard } from '../context/WizardContext';

const Results: React.FC = () => {
  const { state, resetWizard } = useWizard();

  const handleNewDeployment = () => {
    resetWizard();
  };

  const handleViewDashboard = () => {
    // Navigate to dashboard or management interface
    window.alert('Dashboard feature coming soon!');
  };

  // Build URLs from infrastructure config
  const domainConfig = state.infrastructureConfig?.infrastructure?.domain;
  const baseDomain = domainConfig?.base || 'example.com';
  const frontendSubdomain = domainConfig?.frontend_subdomain || 'app';
  const backendSubdomain = domainConfig?.backend_subdomain || 'api';
  
  const frontendUrl = state.deploymentStatus.frontend_url || 
    `https://${frontendSubdomain}.${baseDomain}`;
  const backendUrl = state.deploymentStatus.backend_url || 
    `https://${backendSubdomain}.${baseDomain}`;

  // Get Cognito admin user info
  const cognitoConfig = state.deploymentStatus.cognito_config;
  const adminUserEmail = cognitoConfig?.admin_user_email || 
    `admin@${state.selectedCapability?.name?.toLowerCase().replace(/\s+/g, '-')}.local`;
  const adminTempPassword = cognitoConfig?.admin_temp_password || 'Admin@Temp123!';

  const deploymentOutputs = [
    {
      name: 'Frontend Application URL',
      value: frontendUrl,
      description: 'Access your deployed application here',
      copyable: true,
      isLink: true,
    },
    {
      name: 'Backend API URL',
      value: backendUrl,
      description: 'Backend API endpoint for your application',
      copyable: true,
      isLink: true,
    },
    {
      name: 'Cognito User Pool ID',
      value: state.deploymentStatus.cognito_user_pool_id || cognitoConfig?.user_pool_id || 'Available in AWS Console',
      description: 'User authentication pool for managing users',
      copyable: !!(state.deploymentStatus.cognito_user_pool_id || cognitoConfig?.user_pool_id),
    },
    {
      name: 'AWS Region',
      value: state.awsConfig?.region || 'N/A',
      description: 'Deployment region',
      copyable: true,
    },
  ];

  const accessInstructions = [
    {
      title: '1. Access Your Application',
      description: `Open ${frontendUrl} in your browser to access the deployed application.`,
      icon: '🌐',
    },
    {
      title: '2. First-Time Admin Login',
      description: `Login with username: ${adminUserEmail} and the temporary password shown above.`,
      icon: '🔐',
      highlight: true,
    },
    {
      title: '3. Set New Password',
      description: 'On first login, you must set a new password. Requirements: 12+ characters, uppercase, lowercase, numbers, and symbols.',
      icon: '🔑',
    },
    {
      title: '4. Create Additional Users',
      description: 'Go to AWS Cognito Console > User Pools to create additional users or configure user self-registration.',
      icon: '👥',
    },
  ];

  const nextSteps = [
    {
      title: 'Monitor Resources',
      description: 'Use CloudWatch to monitor your deployed resources and set up alarms',
      icon: '📊',
    },
    {
      title: 'Review Documentation',
      description: 'Check the capability documentation for advanced configuration options',
      icon: '📚',
    },
    {
      title: 'Set Up CI/CD',
      description: 'Configure continuous deployment for automatic updates',
      icon: '🔄',
    },
  ];

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    // Could add a toast notification here
  };

  return (
    <div className="max-w-5xl mx-auto">
      {/* Success Header */}
      <div className="text-center mb-8">
        <div className="inline-flex items-center justify-center w-20 h-20 bg-green-100 rounded-full mb-4">
          <svg className="w-12 h-12 text-green-600" fill="currentColor" viewBox="0 0 20 20">
            <path
              fillRule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
              clipRule="evenodd"
            />
          </svg>
        </div>
        <h1 className="text-4xl font-bold text-gray-900 mb-2">Deployment Successful!</h1>
        <p className="text-xl text-gray-600">
          {state.selectedCapability?.name} has been deployed to {state.selectedEnvironment}
        </p>
      </div>

      {/* Deployment Summary */}
      <div className="bg-white rounded-lg shadow-md p-6 mb-6">
        <h2 className="text-2xl font-semibold text-gray-900 mb-4">Deployment Summary</h2>
        
        <div className="grid grid-cols-2 gap-6 mb-6">
          <div>
            <p className="text-sm font-medium text-gray-500">Capability</p>
            <p className="text-lg text-gray-900">{state.selectedCapability?.name}</p>
          </div>
          <div>
            <p className="text-sm font-medium text-gray-500">Version</p>
            <p className="text-lg text-gray-900">{state.selectedCapability?.version}</p>
          </div>
          <div>
            <p className="text-sm font-medium text-gray-500">Environment</p>
            <p className="text-lg text-gray-900">{state.selectedEnvironment}</p>
          </div>
          <div>
            <p className="text-sm font-medium text-gray-500">Region</p>
            <p className="text-lg text-gray-900">{state.awsConfig?.region}</p>
          </div>
        </div>

        <div className="border-t pt-4">
          <p className="text-sm text-gray-600">
            Deployed on {new Date().toLocaleDateString()} at {new Date().toLocaleTimeString()}
          </p>
        </div>
      </div>

      {/* Deployment Outputs */}
      <div className="bg-white rounded-lg shadow-md p-6 mb-6">
        <h2 className="text-2xl font-semibold text-gray-900 mb-4">Deployment Outputs</h2>
        
        <div className="space-y-4">
          {deploymentOutputs.map((output, index) => (
            <div key={index} className="border border-gray-200 rounded-lg p-4">
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <h3 className="font-medium text-gray-900">{output.name}</h3>
                  <p className="text-sm text-gray-600 mt-1">{output.description}</p>
                  <div className="mt-2 flex items-center">
                    {output.isLink ? (
                      <a
                        href={output.value}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sm bg-blue-50 px-3 py-1 rounded font-mono text-blue-700 hover:bg-blue-100"
                      >
                        {output.value} →
                      </a>
                    ) : (
                      <code className="text-sm bg-gray-100 px-3 py-1 rounded font-mono text-gray-800">
                        {output.value}
                      </code>
                    )}
                    {output.copyable && (
                      <button
                        onClick={() => copyToClipboard(output.value)}
                        className="ml-2 text-blue-600 hover:text-blue-800"
                        title="Copy to clipboard"
                      >
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"
                          />
                        </svg>
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* First-Time Login Credentials */}
      <div className="bg-amber-50 border-2 border-amber-300 rounded-lg shadow-md p-6 mb-6">
        <div className="flex items-start">
          <div className="flex-shrink-0 w-12 h-12 bg-amber-100 rounded-lg flex items-center justify-center text-2xl mr-4">
            🔐
          </div>
          <div className="flex-1">
            <h2 className="text-2xl font-semibold text-amber-800 mb-2">First-Time Login Credentials</h2>
            <p className="text-amber-700 mb-4">
              An admin user has been created for your application. Use these credentials for your first login.
            </p>
            
            <div className="bg-white rounded-lg p-4 border border-amber-200">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <p className="text-sm font-medium text-gray-500 mb-1">Admin Username (Email)</p>
                  <div className="flex items-center">
                    <code className="text-sm bg-amber-100 px-3 py-2 rounded font-mono text-amber-900 flex-1">
                      {adminUserEmail}
                    </code>
                    <button
                      onClick={() => copyToClipboard(adminUserEmail)}
                      className="ml-2 text-amber-600 hover:text-amber-800 p-1"
                      title="Copy to clipboard"
                    >
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"
                        />
                      </svg>
                    </button>
                  </div>
                </div>
                <div>
                  <p className="text-sm font-medium text-gray-500 mb-1">Temporary Password</p>
                  <div className="flex items-center">
                    <code className="text-sm bg-red-100 px-3 py-2 rounded font-mono text-red-900 flex-1">
                      {adminTempPassword}
                    </code>
                    <button
                      onClick={() => copyToClipboard(adminTempPassword)}
                      className="ml-2 text-red-600 hover:text-red-800 p-1"
                      title="Copy to clipboard"
                    >
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"
                        />
                      </svg>
                    </button>
                  </div>
                </div>
              </div>
              
              <div className="mt-4 pt-4 border-t border-amber-200">
                <p className="text-sm text-amber-700">
                  <span className="font-semibold">⚠️ Important:</span> On first login, you will be prompted to change your password. 
                  Password requirements: 12+ characters, uppercase, lowercase, numbers, and symbols.
                </p>
              </div>
            </div>

            {/* Test Users Info (if available) */}
            {cognitoConfig?.test_users_info && (state.selectedEnvironment === 'dev' || state.selectedEnvironment === 'prod') && (
              <div className="mt-4 bg-white rounded-lg p-4 border border-amber-200">
                <p className="text-sm font-medium text-gray-700 mb-2">Additional Test Users (Dev/Prod only):</p>
                <p className="text-xs text-gray-500 mb-2">All test users use the same temporary password: <code className="bg-gray-100 px-1 rounded">{adminTempPassword}</code></p>
                <pre className="text-xs bg-gray-50 p-3 rounded font-mono text-gray-600 whitespace-pre-wrap">
                  {cognitoConfig.test_users_info}
                </pre>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Application Access Instructions */}
      <div className="bg-green-50 border border-green-200 rounded-lg shadow-md p-6 mb-6">
        <h2 className="text-2xl font-semibold text-green-800 mb-4">🚀 How to Access Your Application</h2>
        
        <div className="space-y-4">
          {accessInstructions.map((step, index) => (
            <div key={index} className="flex items-start">
              <div className="flex-shrink-0 w-10 h-10 bg-green-100 rounded-lg flex items-center justify-center text-2xl mr-4">
                {step.icon}
              </div>
              <div className="flex-1">
                <h3 className="font-medium text-green-900">{step.title}</h3>
                <p className="text-sm text-green-700 mt-1">{step.description}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Next Steps */}
      <div className="bg-white rounded-lg shadow-md p-6 mb-6">
        <h2 className="text-2xl font-semibold text-gray-900 mb-4">Next Steps</h2>
        
        <div className="space-y-4">
          {nextSteps.map((step, index) => (
            <div key={index} className="flex items-start">
              <div className="flex-shrink-0 w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center text-2xl mr-4">
                {step.icon}
              </div>
              <div className="flex-1">
                <h3 className="font-medium text-gray-900">{step.title}</h3>
                <p className="text-sm text-gray-600 mt-1">{step.description}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Action Buttons */}
      <div className="flex justify-center gap-4">
        <button
          onClick={handleViewDashboard}
          className="px-8 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium"
        >
          View Dashboard
        </button>
        <button
          onClick={handleNewDeployment}
          className="px-8 py-3 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 font-medium"
        >
          New Deployment
        </button>
      </div>

      {/* Support Information */}
      <div className="mt-8 text-center text-sm text-gray-600">
        <p>Need help? Check the documentation or contact support.</p>
        <div className="mt-2 space-x-4">
          <a href="#" className="text-blue-600 hover:text-blue-800">
            Documentation
          </a>
          <span>•</span>
          <a href="#" className="text-blue-600 hover:text-blue-800">
            Support
          </a>
          <span>•</span>
          <a href="#" className="text-blue-600 hover:text-blue-800">
            Community
          </a>
        </div>
      </div>
    </div>
  );
};

export default Results;
