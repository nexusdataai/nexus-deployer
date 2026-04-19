/**
 * IAM Setup Guide Modal Component
 * Provides step-by-step IAM role setup instructions
 */
import React, { useState } from 'react';
import { generateFullDeploymentPolicy, downloadPolicy, formatPolicyForDownload } from '../utils/policy-generator';

interface IAMSetupGuideModalProps {
  isOpen: boolean;
  onClose: () => void;
  sourceAccountId?: string;
  targetAccountId?: string;
  isCrossAccount?: boolean;
}

type SetupMethod = 'cloudformation' | 'cli' | 'manual';

const IAMSetupGuideModal: React.FC<IAMSetupGuideModalProps> = ({
  isOpen,
  onClose,
  sourceAccountId = 'SOURCE_ACCOUNT_ID',
  targetAccountId: _targetAccountId,
  isCrossAccount = false
}) => {
  const [selectedMethod, setSelectedMethod] = useState<SetupMethod>('cloudformation');
  const [externalId] = useState('totogi-deployment-' + Math.random().toString(36).substring(7));
  const [roleName] = useState('TotogiDeploymentRole');
  const [copiedCommand, setCopiedCommand] = useState<string | null>(null);
  
  // Suppress unused variable warning
  void _targetAccountId;

  if (!isOpen) return null;

  const copyToClipboard = async (text: string, commandId: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedCommand(commandId);
      setTimeout(() => setCopiedCommand(null), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  const trustPolicy = isCrossAccount
    ? `{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::${sourceAccountId}:root"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "sts:ExternalId": "${externalId}"
        }
      }
    }
  ]
}`
    : `{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "cloudformation.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}`;

  const cliCreateRoleCommand = `aws iam create-role \\
  --role-name ${roleName} \\
  --assume-role-policy-document file://trust-policy.json \\
  --description "Role for Totogi capability deployment"`;

  const cliAttachPolicyCommand = `aws iam put-role-policy \\
  --role-name ${roleName} \\
  --policy-name TotogiDeploymentPolicy \\
  --policy-document file://deployment-role-policy.json`;

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      {/* Backdrop */}
      <div 
        className="fixed inset-0 bg-black bg-opacity-50 transition-opacity"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="flex min-h-full items-center justify-center p-4">
        <div className="relative bg-white rounded-xl shadow-xl max-w-3xl w-full max-h-[90vh] overflow-hidden">
          {/* Header */}
          <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
            <h2 className="text-xl font-semibold text-gray-900">IAM Role Setup Guide</h2>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-600 transition-colors"
            >
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* Tab Navigation */}
          <div className="px-6 pt-4 border-b border-gray-200">
            <div className="flex space-x-4">
              {[
                { id: 'cloudformation', label: 'CloudFormation', icon: '📦' },
                { id: 'cli', label: 'AWS CLI', icon: '💻' },
                { id: 'manual', label: 'Manual Setup', icon: '📝' }
              ].map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setSelectedMethod(tab.id as SetupMethod)}
                  className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                    selectedMethod === tab.id
                      ? 'border-blue-500 text-blue-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700'
                  }`}
                >
                  <span className="mr-1">{tab.icon}</span>
                  {tab.label}
                </button>
              ))}
            </div>
          </div>

          {/* Content */}
          <div className="p-6 overflow-y-auto max-h-[60vh]">
            {/* Cross-Account Warning */}
            {isCrossAccount && (
              <div className="mb-4 p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
                <div className="flex items-start">
                  <svg className="w-5 h-5 text-yellow-600 mr-2 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                  </svg>
                  <div className="text-sm text-yellow-800">
                    <p className="font-medium">Cross-Account Deployment Detected</p>
                    <p className="mt-1">
                      You're deploying to a different AWS account. The trust policy must include the source account ID
                      and an external ID for security.
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* CloudFormation Tab */}
            {selectedMethod === 'cloudformation' && (
              <div className="space-y-4">
                <div>
                  <h3 className="text-lg font-medium text-gray-900 mb-2">Deploy via CloudFormation</h3>
                  <p className="text-sm text-gray-600 mb-4">
                    The fastest way to set up the IAM role is using our CloudFormation template.
                  </p>
                </div>

                <div className="space-y-3">
                  <div className="flex items-center">
                    <span className="flex items-center justify-center w-6 h-6 bg-blue-100 text-blue-600 rounded-full text-sm font-medium mr-3">1</span>
                    <span className="text-sm text-gray-700">Download the IAM policy with all required permissions</span>
                  </div>
                  <div className="ml-9 flex space-x-2">
                    <button 
                      onClick={() => downloadPolicy(generateFullDeploymentPolicy(), 'deployment-role-policy.json')}
                      className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
                    >
                      Download IAM Policy
                    </button>
                    <button 
                      onClick={() => copyToClipboard(formatPolicyForDownload(generateFullDeploymentPolicy()), 'iam-policy')}
                      className="px-4 py-2 bg-gray-200 text-gray-700 text-sm rounded-lg hover:bg-gray-300"
                    >
                      {copiedCommand === 'iam-policy' ? 'Copied!' : 'Copy to Clipboard'}
                    </button>
                  </div>

                  <div className="flex items-center mt-4">
                    <span className="flex items-center justify-center w-6 h-6 bg-blue-100 text-blue-600 rounded-full text-sm font-medium mr-3">2</span>
                    <span className="text-sm text-gray-700">Create the IAM role with the downloaded policy</span>
                  </div>
                  <div className="ml-9">
                    <div className="bg-gray-900 rounded-lg p-3 relative">
                      <pre className="text-sm text-gray-100 overflow-x-auto">
{`aws iam create-role \\
  --role-name ${roleName} \\
  --assume-role-policy-document '${isCrossAccount ? trustPolicy : `{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "cloudformation.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }`}'`}
                      </pre>
                      <button
                        onClick={() => copyToClipboard(`aws iam create-role --role-name ${roleName} --assume-role-policy-document '${isCrossAccount ? trustPolicy.replace(/\n/g, ' ') : '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"cloudformation.amazonaws.com"},"Action":"sts:AssumeRole"}]}'}'`, 'create-role-cf')}
                        className="absolute top-2 right-2 p-1 text-gray-400 hover:text-white"
                      >
                        {copiedCommand === 'create-role-cf' ? (
                          <svg className="w-5 h-5 text-green-400" fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                          </svg>
                        ) : (
                          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                          </svg>
                        )}
                      </button>
                    </div>
                  </div>

                  <div className="flex items-center mt-4">
                    <span className="flex items-center justify-center w-6 h-6 bg-blue-100 text-blue-600 rounded-full text-sm font-medium mr-3">3</span>
                    <span className="text-sm text-gray-700">Attach the deployment policy to the role</span>
                  </div>
                  <div className="ml-9">
                    <div className="bg-gray-900 rounded-lg p-3 relative">
                      <pre className="text-sm text-gray-100 overflow-x-auto">
{`aws iam put-role-policy \\
  --role-name ${roleName} \\
  --policy-name TotogiDeploymentPolicy \\
  --policy-document file://deployment-role-policy.json`}
                      </pre>
                      <button
                        onClick={() => copyToClipboard(`aws iam put-role-policy --role-name ${roleName} --policy-name TotogiDeploymentPolicy --policy-document file://deployment-role-policy.json`, 'cf-command')}
                        className="absolute top-2 right-2 p-1 text-gray-400 hover:text-white"
                      >
                        {copiedCommand === 'cf-command' ? (
                          <svg className="w-5 h-5 text-green-400" fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                          </svg>
                        ) : (
                          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                          </svg>
                        )}
                      </button>
                    </div>
                  </div>

                  <div className="flex items-center mt-4">
                    <span className="flex items-center justify-center w-6 h-6 bg-blue-100 text-blue-600 rounded-full text-sm font-medium mr-3">4</span>
                    <span className="text-sm text-gray-700">Copy the Role ARN for use in the wizard</span>
                  </div>
                  <div className="ml-9">
                    <div className="bg-gray-900 rounded-lg p-3 relative">
                      <pre className="text-sm text-gray-100 overflow-x-auto">
{`aws iam get-role --role-name ${roleName} --query 'Role.Arn' --output text`}
                      </pre>
                      <button
                        onClick={() => copyToClipboard(`aws iam get-role --role-name ${roleName} --query 'Role.Arn' --output text`, 'get-arn')}
                        className="absolute top-2 right-2 p-1 text-gray-400 hover:text-white"
                      >
                        {copiedCommand === 'get-arn' ? (
                          <svg className="w-5 h-5 text-green-400" fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                          </svg>
                        ) : (
                          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                          </svg>
                        )}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* CLI Tab */}
            {selectedMethod === 'cli' && (
              <div className="space-y-4">
                <div>
                  <h3 className="text-lg font-medium text-gray-900 mb-2">Setup via AWS CLI</h3>
                  <p className="text-sm text-gray-600 mb-4">
                    Create the IAM role using AWS CLI commands.
                  </p>
                </div>

                <div className="space-y-4">
                  {/* Step 1: Create trust policy file */}
                  <div>
                    <div className="flex items-center mb-2">
                      <span className="flex items-center justify-center w-6 h-6 bg-blue-100 text-blue-600 rounded-full text-sm font-medium mr-3">1</span>
                      <span className="text-sm font-medium text-gray-700">Create trust-policy.json</span>
                    </div>
                    <div className="ml-9 bg-gray-900 rounded-lg p-3 relative">
                      <pre className="text-sm text-gray-100 overflow-x-auto">{trustPolicy}</pre>
                      <button
                        onClick={() => copyToClipboard(trustPolicy, 'trust-policy')}
                        className="absolute top-2 right-2 p-1 text-gray-400 hover:text-white"
                      >
                        {copiedCommand === 'trust-policy' ? (
                          <svg className="w-5 h-5 text-green-400" fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                          </svg>
                        ) : (
                          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                          </svg>
                        )}
                      </button>
                    </div>
                  </div>

                  {/* Step 2: Create role */}
                  <div>
                    <div className="flex items-center mb-2">
                      <span className="flex items-center justify-center w-6 h-6 bg-blue-100 text-blue-600 rounded-full text-sm font-medium mr-3">2</span>
                      <span className="text-sm font-medium text-gray-700">Create the IAM role</span>
                    </div>
                    <div className="ml-9 bg-gray-900 rounded-lg p-3 relative">
                      <pre className="text-sm text-gray-100 overflow-x-auto">{cliCreateRoleCommand}</pre>
                      <button
                        onClick={() => copyToClipboard(cliCreateRoleCommand.replace(/\\\n/g, ' '), 'create-role')}
                        className="absolute top-2 right-2 p-1 text-gray-400 hover:text-white"
                      >
                        {copiedCommand === 'create-role' ? (
                          <svg className="w-5 h-5 text-green-400" fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                          </svg>
                        ) : (
                          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                          </svg>
                        )}
                      </button>
                    </div>
                  </div>

                  {/* Step 3: Attach policy */}
                  <div>
                    <div className="flex items-center mb-2">
                      <span className="flex items-center justify-center w-6 h-6 bg-blue-100 text-blue-600 rounded-full text-sm font-medium mr-3">3</span>
                      <span className="text-sm font-medium text-gray-700">Attach the deployment policy</span>
                    </div>
                    <div className="ml-9 bg-gray-900 rounded-lg p-3 relative">
                      <pre className="text-sm text-gray-100 overflow-x-auto">{cliAttachPolicyCommand}</pre>
                      <button
                        onClick={() => copyToClipboard(cliAttachPolicyCommand.replace(/\\\n/g, ' '), 'attach-policy')}
                        className="absolute top-2 right-2 p-1 text-gray-400 hover:text-white"
                      >
                        {copiedCommand === 'attach-policy' ? (
                          <svg className="w-5 h-5 text-green-400" fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                          </svg>
                        ) : (
                          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                          </svg>
                        )}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Manual Tab */}
            {selectedMethod === 'manual' && (
              <div className="space-y-4">
                <div>
                  <h3 className="text-lg font-medium text-gray-900 mb-2">Manual Console Setup</h3>
                  <p className="text-sm text-gray-600 mb-4">
                    Follow these steps to create the IAM role in the AWS Console.
                  </p>
                </div>

                <ol className="space-y-4">
                  <li className="flex items-start">
                    <span className="flex items-center justify-center w-6 h-6 bg-blue-100 text-blue-600 rounded-full text-sm font-medium mr-3 mt-0.5">1</span>
                    <div>
                      <p className="text-sm font-medium text-gray-700">Open IAM Console</p>
                      <p className="text-sm text-gray-600 mt-1">
                        Navigate to <a href="https://console.aws.amazon.com/iam" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">IAM Console</a> → Roles → Create role
                      </p>
                    </div>
                  </li>

                  <li className="flex items-start">
                    <span className="flex items-center justify-center w-6 h-6 bg-blue-100 text-blue-600 rounded-full text-sm font-medium mr-3 mt-0.5">2</span>
                    <div>
                      <p className="text-sm font-medium text-gray-700">Select Trusted Entity</p>
                      <p className="text-sm text-gray-600 mt-1">
                        {isCrossAccount 
                          ? 'Choose "AWS account" → "Another AWS account" → Enter the source account ID'
                          : 'Choose "AWS service" → "CloudFormation"'}
                      </p>
                    </div>
                  </li>

                  {isCrossAccount && (
                    <li className="flex items-start">
                      <span className="flex items-center justify-center w-6 h-6 bg-blue-100 text-blue-600 rounded-full text-sm font-medium mr-3 mt-0.5">3</span>
                      <div>
                        <p className="text-sm font-medium text-gray-700">Configure External ID</p>
                        <p className="text-sm text-gray-600 mt-1">
                          Check "Require external ID" and enter: <code className="bg-gray-100 px-1 rounded">{externalId}</code>
                        </p>
                      </div>
                    </li>
                  )}

                  <li className="flex items-start">
                    <span className="flex items-center justify-center w-6 h-6 bg-blue-100 text-blue-600 rounded-full text-sm font-medium mr-3 mt-0.5">{isCrossAccount ? '4' : '3'}</span>
                    <div>
                      <p className="text-sm font-medium text-gray-700">Create Custom Policy</p>
                      <p className="text-sm text-gray-600 mt-1">
                        Skip attaching existing policies. After role creation, add an inline policy with the deployment permissions.
                      </p>
                    </div>
                  </li>

                  <li className="flex items-start">
                    <span className="flex items-center justify-center w-6 h-6 bg-blue-100 text-blue-600 rounded-full text-sm font-medium mr-3 mt-0.5">{isCrossAccount ? '5' : '4'}</span>
                    <div>
                      <p className="text-sm font-medium text-gray-700">Name the Role</p>
                      <p className="text-sm text-gray-600 mt-1">
                        Enter role name: <code className="bg-gray-100 px-1 rounded">{roleName}</code>
                      </p>
                    </div>
                  </li>

                  <li className="flex items-start">
                    <span className="flex items-center justify-center w-6 h-6 bg-blue-100 text-blue-600 rounded-full text-sm font-medium mr-3 mt-0.5">{isCrossAccount ? '6' : '5'}</span>
                    <div>
                      <p className="text-sm font-medium text-gray-700">Copy Role ARN</p>
                      <p className="text-sm text-gray-600 mt-1">
                        After creation, copy the Role ARN from the role summary page.
                      </p>
                    </div>
                  </li>
                </ol>
              </div>
            )}

            {/* Trust Policy Section */}
            {isCrossAccount && (
              <div className="mt-6 p-4 bg-gray-50 border border-gray-200 rounded-lg">
                <h4 className="text-sm font-medium text-gray-900 mb-2">Trust Policy Configuration</h4>
                <p className="text-xs text-gray-600 mb-3">
                  The trust policy allows the source account to assume this role. The external ID provides 
                  additional security against the "confused deputy" attack.
                </p>
                <div className="bg-yellow-50 border border-yellow-200 rounded p-2">
                  <p className="text-xs text-yellow-800">
                    <strong>Security Note:</strong> Never share your external ID publicly. It acts as a shared 
                    secret between accounts.
                  </p>
                </div>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="px-6 py-4 border-t border-gray-200 bg-gray-50 flex justify-end">
            <button
              onClick={onClose}
              className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300 mr-2"
            >
              Close
            </button>
            <a
              href="https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_create.html"
              target="_blank"
              rel="noopener noreferrer"
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              AWS IAM Documentation
            </a>
          </div>
        </div>
      </div>
    </div>
  );
};

export default IAMSetupGuideModal;
