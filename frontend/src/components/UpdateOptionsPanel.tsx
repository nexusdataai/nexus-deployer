/**
 * Update Options Panel Component
 * Displays Cognito preservation options, user data backup, and selective stack update UI
 * 
 * Requirements: 3.1, 3.2, 3.3, 4.1, 4.6, 9.1
 * Feature: update-workflow-cognito-preservation
 */
import React, { useState, useEffect } from 'react';
import { UpdateOptions, DriftDetectionResult, ExistingStackInfo } from '../types/wizard';

interface UpdateOptionsPanelProps {
  stacks: ExistingStackInfo[];
  onOptionsChange: (options: UpdateOptions) => void;
  initialOptions?: UpdateOptions;
  driftResult?: DriftDetectionResult | null;
  isLoadingDrift?: boolean;
  onDetectDrift?: () => void;
}

export const UpdateOptionsPanel: React.FC<UpdateOptionsPanelProps> = ({
  stacks,
  onOptionsChange,
  initialOptions,
  driftResult,
  isLoadingDrift = false,
  onDetectDrift,
}) => {
  const [preserveCognito, setPreserveCognito] = useState(
    initialOptions?.preserveCognito ?? true
  );
  const [includeCognitoUpdate, setIncludeCognitoUpdate] = useState(
    initialOptions?.includeCognitoUpdate ?? false
  );
  const [requireUserBackup, setRequireUserBackup] = useState(
    initialOptions?.requireUserBackup ?? true
  );
  const [selectedStacks, setSelectedStacks] = useState<string[] | null>(
    initialOptions?.selectedStacks ?? null
  );
  const [showSelectiveUpdate, setShowSelectiveUpdate] = useState(false);
  const [showCognitoWarning, setShowCognitoWarning] = useState(false);

  // Find Cognito stack
  const cognitoStack = stacks.find(
    (s) => s.stack_type.toLowerCase().includes('cognito')
  );
  const hasCognitoStack = !!cognitoStack;

  // Update parent when options change
  useEffect(() => {
    onOptionsChange({
      preserveCognito,
      includeCognitoUpdate,
      requireUserBackup,
      selectedStacks,
      skipDriftDetection: false,
    });
  }, [preserveCognito, includeCognitoUpdate, requireUserBackup, selectedStacks, onOptionsChange]);

  const handleCognitoUpdateToggle = (include: boolean) => {
    if (include) {
      setShowCognitoWarning(true);
    } else {
      setIncludeCognitoUpdate(false);
      setPreserveCognito(true);
    }
  };

  const confirmCognitoUpdate = () => {
    setIncludeCognitoUpdate(true);
    setPreserveCognito(false);
    setShowCognitoWarning(false);
  };

  const handleStackSelection = (stackName: string, selected: boolean) => {
    if (selectedStacks === null) {
      // First selection - start with all stacks selected except the one being toggled
      const allStackNames = stacks.map((s) => s.stack_name);
      if (selected) {
        setSelectedStacks(allStackNames);
      } else {
        setSelectedStacks(allStackNames.filter((n) => n !== stackName));
      }
    } else {
      if (selected) {
        setSelectedStacks([...selectedStacks, stackName]);
      } else {
        setSelectedStacks(selectedStacks.filter((n) => n !== stackName));
      }
    }
  };

  const selectAllStacks = () => {
    setSelectedStacks(stacks.map((s) => s.stack_name));
  };

  const deselectAllStacks = () => {
    setSelectedStacks([]);
  };

  return (
    <div className="space-y-6">
      {/* Cognito Preservation Section */}
      {hasCognitoStack && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
          <div className="flex items-start">
            <svg
              className="w-6 h-6 text-blue-600 mr-3 flex-shrink-0 mt-0.5"
              fill="currentColor"
              viewBox="0 0 20 20"
            >
              <path
                fillRule="evenodd"
                d="M18 8a6 6 0 01-7.743 5.743L10 14l-1 1-1 1H6v2H2v-4l4.257-4.257A6 6 0 1118 8zm-6-4a1 1 0 100 2 2 2 0 012 2 1 1 0 102 0 4 4 0 00-4-4z"
                clipRule="evenodd"
              />
            </svg>
            <div className="flex-1">
              <h3 className="font-semibold text-blue-900 mb-2">
                Cognito User Pool Detected
              </h3>
              <p className="text-sm text-blue-800 mb-3">
                Your deployment includes a Cognito User Pool with existing user data.
                By default, this will be preserved during the update.
              </p>

              {/* Cognito Preservation Toggle */}
              <div className="space-y-3">
                <label className="flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={preserveCognito && !includeCognitoUpdate}
                    onChange={(e) => {
                      if (e.target.checked) {
                        setPreserveCognito(true);
                        setIncludeCognitoUpdate(false);
                      } else {
                        handleCognitoUpdateToggle(true);
                      }
                    }}
                    className="w-4 h-4 text-blue-600 rounded focus:ring-blue-500"
                  />
                  <span className="ml-2 text-sm text-blue-900">
                    Preserve Cognito User Pool (recommended)
                  </span>
                </label>

                {includeCognitoUpdate && (
                  <div className="ml-6 space-y-2">
                    <div className="bg-yellow-50 border border-yellow-300 rounded p-3">
                      <p className="text-sm font-medium text-yellow-900 mb-1">
                        ⚠️ Cognito Update Enabled
                      </p>
                      <p className="text-xs text-yellow-800">
                        Updating Cognito may affect user data. CloudFormation update
                        semantics will be used to minimize data loss.
                      </p>
                    </div>

                    {/* User Backup Option */}
                    <label className="flex items-center cursor-pointer">
                      <input
                        type="checkbox"
                        checked={requireUserBackup}
                        onChange={(e) => setRequireUserBackup(e.target.checked)}
                        className="w-4 h-4 text-yellow-600 rounded focus:ring-yellow-500"
                      />
                      <span className="ml-2 text-sm text-yellow-900">
                        Export user data before update (recommended)
                      </span>
                    </label>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Cognito Update Warning Modal */}
      {showCognitoWarning && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4 p-6">
            <div className="flex items-start mb-4">
              <svg
                className="w-8 h-8 text-yellow-500 mr-3 flex-shrink-0"
                fill="currentColor"
                viewBox="0 0 20 20"
              >
                <path
                  fillRule="evenodd"
                  d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z"
                  clipRule="evenodd"
                />
              </svg>
              <div>
                <h3 className="text-lg font-bold text-gray-900 mb-2">
                  Warning: Cognito Update
                </h3>
                <p className="text-sm text-gray-700 mb-3">
                  Updating the Cognito stack may affect user data. While CloudFormation
                  will attempt to update in place, some changes may require resource
                  replacement.
                </p>
                <p className="text-sm text-gray-700 mb-4">
                  <strong>Potential impacts:</strong>
                </p>
                <ul className="text-sm text-gray-600 list-disc ml-4 mb-4 space-y-1">
                  <li>User passwords may be reset</li>
                  <li>MFA configurations may be lost</li>
                  <li>Custom attributes may be affected</li>
                  <li>Active sessions may be invalidated</li>
                </ul>
              </div>
            </div>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setShowCognitoWarning(false)}
                className="px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={confirmCognitoUpdate}
                className="px-4 py-2 bg-yellow-600 text-white rounded-lg hover:bg-yellow-700"
              >
                I Understand, Include Cognito
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Drift Detection Section */}
      {hasCognitoStack && onDetectDrift && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold text-gray-900">Configuration Drift Detection</h3>
            <button
              onClick={onDetectDrift}
              disabled={isLoadingDrift}
              className="px-3 py-1 text-sm bg-gray-200 text-gray-700 rounded hover:bg-gray-300 disabled:opacity-50 flex items-center"
            >
              {isLoadingDrift ? (
                <>
                  <svg
                    className="animate-spin w-4 h-4 mr-1"
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
                  Detecting...
                </>
              ) : (
                'Check for Drift'
              )}
            </button>
          </div>

          {driftResult && <DriftDisplay result={driftResult} />}

          {!driftResult && !isLoadingDrift && (
            <p className="text-sm text-gray-600">
              Click "Check for Drift" to compare deployed Cognito configuration with the
              template.
            </p>
          )}
        </div>
      )}

      {/* Selective Stack Update Section */}
      <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-gray-900">Selective Stack Update</h3>
          <button
            onClick={() => setShowSelectiveUpdate(!showSelectiveUpdate)}
            className="text-sm text-blue-600 hover:text-blue-800"
          >
            {showSelectiveUpdate ? 'Hide Options' : 'Show Options'}
          </button>
        </div>

        {!showSelectiveUpdate && (
          <p className="text-sm text-gray-600">
            By default, all stacks will be updated. Click "Show Options" to select
            specific stacks.
          </p>
        )}

        {showSelectiveUpdate && (
          <div className="space-y-3">
            <div className="flex gap-2 mb-2">
              <button
                onClick={selectAllStacks}
                className="text-xs text-blue-600 hover:text-blue-800"
              >
                Select All
              </button>
              <span className="text-gray-400">|</span>
              <button
                onClick={deselectAllStacks}
                className="text-xs text-blue-600 hover:text-blue-800"
              >
                Deselect All
              </button>
            </div>

            <div className="space-y-2 max-h-48 overflow-y-auto">
              {stacks.map((stack) => {
                const isCognito = stack.stack_type.toLowerCase().includes('cognito');
                const isSelected =
                  selectedStacks === null || selectedStacks.includes(stack.stack_name);
                const isDisabled = isCognito && preserveCognito && !includeCognitoUpdate;

                return (
                  <label
                    key={stack.stack_name}
                    className={`flex items-center p-2 rounded border ${
                      isDisabled
                        ? 'bg-gray-100 border-gray-200 cursor-not-allowed'
                        : isSelected
                        ? 'bg-blue-50 border-blue-200 cursor-pointer'
                        : 'bg-white border-gray-200 cursor-pointer hover:bg-gray-50'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={isSelected && !isDisabled}
                      disabled={isDisabled}
                      onChange={(e) =>
                        handleStackSelection(stack.stack_name, e.target.checked)
                      }
                      className="w-4 h-4 text-blue-600 rounded focus:ring-blue-500"
                    />
                    <div className="ml-3 flex-1">
                      <span className="text-sm font-medium text-gray-900">
                        {stack.stack_type}
                      </span>
                      {isCognito && (
                        <span className="ml-2 text-xs bg-yellow-100 text-yellow-800 px-2 py-0.5 rounded">
                          Contains User Data
                        </span>
                      )}
                      {isDisabled && (
                        <span className="ml-2 text-xs text-gray-500">
                          (Preserved)
                        </span>
                      )}
                    </div>
                    <span
                      className={`text-xs px-2 py-0.5 rounded ${
                        stack.classification === 'updatable'
                          ? 'bg-green-100 text-green-800'
                          : stack.classification === 'failed'
                          ? 'bg-red-100 text-red-800'
                          : 'bg-yellow-100 text-yellow-800'
                      }`}
                    >
                      {stack.classification}
                    </span>
                  </label>
                );
              })}
            </div>

            {selectedStacks !== null && selectedStacks.length === 0 && (
              <p className="text-sm text-yellow-600">
                ⚠️ No stacks selected. At least one stack must be selected for update.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

/**
 * Drift Display Component
 * Shows drift detection results
 * Requirements: 5.3, 5.4
 */
interface DriftDisplayProps {
  result: DriftDetectionResult;
}

const DriftDisplay: React.FC<DriftDisplayProps> = ({ result }) => {
  if (result.error_message) {
    return (
      <div className="bg-yellow-50 border border-yellow-200 rounded p-3">
        <p className="text-sm text-yellow-800">
          ⚠️ Drift detection failed: {result.error_message}
        </p>
        <p className="text-xs text-yellow-700 mt-1">
          You can proceed with the update, but drift status is unknown.
        </p>
      </div>
    );
  }

  if (!result.has_drift) {
    return (
      <div className="bg-green-50 border border-green-200 rounded p-3">
        <div className="flex items-center">
          <svg
            className="w-5 h-5 text-green-600 mr-2"
            fill="currentColor"
            viewBox="0 0 20 20"
          >
            <path
              fillRule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
              clipRule="evenodd"
            />
          </svg>
          <span className="text-sm text-green-800">
            No configuration drift detected. Deployed configuration matches template.
          </span>
        </div>
      </div>
    );
  }

  // Group drift items by category
  const byCategory: Record<string, typeof result.drift_items> = {};
  result.drift_items.forEach((item) => {
    if (!byCategory[item.category]) {
      byCategory[item.category] = [];
    }
    byCategory[item.category].push(item);
  });

  const categoryLabels: Record<string, string> = {
    password_policy: 'Password Policy',
    mfa: 'MFA Configuration',
    app_client: 'App Client Settings',
    custom_attributes: 'Custom Attributes',
  };

  return (
    <div className="bg-yellow-50 border border-yellow-200 rounded p-3">
      <div className="flex items-start mb-2">
        <svg
          className="w-5 h-5 text-yellow-600 mr-2 flex-shrink-0 mt-0.5"
          fill="currentColor"
          viewBox="0 0 20 20"
        >
          <path
            fillRule="evenodd"
            d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z"
            clipRule="evenodd"
          />
        </svg>
        <div className="flex-1">
          <p className="text-sm font-medium text-yellow-900">
            Configuration drift detected ({result.drift_items.length} items)
          </p>
          <p className="text-xs text-yellow-800 mt-1">
            The deployed Cognito configuration differs from the template.
          </p>
        </div>
      </div>

      <div className="mt-3 space-y-2">
        {Object.entries(byCategory).map(([category, items]) => (
          <div key={category} className="bg-white rounded p-2 border border-yellow-100">
            <p className="text-xs font-medium text-gray-700 mb-1">
              {categoryLabels[category] || category}
            </p>
            <div className="space-y-1">
              {items.map((item, idx) => (
                <div key={idx} className="text-xs text-gray-600">
                  <span className="font-mono">{item.setting_name}</span>:
                  <span className="text-red-600 ml-1">
                    deployed={item.deployed_value}
                  </span>
                  <span className="text-green-600 ml-1">
                    template={item.template_value}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default UpdateOptionsPanel;
