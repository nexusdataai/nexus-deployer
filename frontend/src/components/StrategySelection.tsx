/**
 * Strategy Selection Component
 * Allows users to choose between clean deployment and update deployment
 * 
 * Feature: update-workflow-cognito-preservation
 * Requirements: 1.1, 1.2, 1.3, 1.4, 3.1, 3.2, 3.3, 4.1, 4.6, 9.1
 */
import React, { useState, useCallback } from 'react';
import { StackDetectionResult, DeploymentStrategy, UpdateOptions, DriftDetectionResult } from '../types/wizard';
import { UpdateOptionsPanel } from './UpdateOptionsPanel';

interface StrategySelectionProps {
  detectionResult: StackDetectionResult;
  onStrategySelected: (strategy: DeploymentStrategy, updateOptions?: UpdateOptions) => void;
  onCancel: () => void;
  onCompleteCleanup?: () => void;
  onDetectDrift?: () => Promise<DriftDetectionResult | null>;
}

export const StrategySelection: React.FC<StrategySelectionProps> = ({
  detectionResult,
  onStrategySelected,
  onCancel,
  onCompleteCleanup,
  onDetectDrift,
}) => {
  // Pre-select recommended strategy if available
  const [selectedStrategy, setSelectedStrategy] = useState<DeploymentStrategy | null>(
    detectionResult.recommended_strategy || null
  );
  const [showCleanupConfirm, setShowCleanupConfirm] = useState(false);
  
  // Update options state
  const [updateOptions, setUpdateOptions] = useState<UpdateOptions>({
    preserveCognito: true,
    includeCognitoUpdate: false,
    requireUserBackup: true,
    selectedStacks: null,
    skipDriftDetection: false,
  });
  const [driftResult, setDriftResult] = useState<DriftDetectionResult | null>(null);
  const [isLoadingDrift, setIsLoadingDrift] = useState(false);

  const handleContinue = () => {
    if (selectedStrategy) {
      if (selectedStrategy === DeploymentStrategy.UPDATE_EXISTING) {
        onStrategySelected(selectedStrategy, updateOptions);
      } else {
        onStrategySelected(selectedStrategy);
      }
    }
  };

  const handleCompleteCleanup = () => {
    if (onCompleteCleanup) {
      onCompleteCleanup();
      setShowCleanupConfirm(false);
    }
  };

  const handleDetectDrift = useCallback(async () => {
    if (onDetectDrift) {
      setIsLoadingDrift(true);
      try {
        const result = await onDetectDrift();
        setDriftResult(result);
      } catch (error) {
        console.error('Drift detection failed:', error);
      } finally {
        setIsLoadingDrift(false);
      }
    }
  }, [onDetectDrift]);

  const handleUpdateOptionsChange = useCallback((options: UpdateOptions) => {
    setUpdateOptions(options);
  }, []);

  const canUpdate = detectionResult.is_updatable && !detectionResult.has_failed_stacks;
  const hasRecommendation = detectionResult.recommended_strategy !== null && detectionResult.recommended_strategy !== undefined;

  return (
    <div className="max-w-4xl mx-auto p-6">
      <div className="bg-white rounded-lg shadow-lg p-8">
        {/* Header */}
        <div className="mb-6">
          <h2 className="text-2xl font-bold text-gray-900 mb-2">
            {detectionResult.has_existing_stacks ? 'Existing Installation Detected' : 'No Existing Installation'}
          </h2>
          <p className="text-gray-600">
            {detectionResult.has_existing_stacks 
              ? 'We found an existing installation of this capability. Please choose how you\'d like to proceed.'
              : 'This appears to be a first-time deployment. No existing stacks were found.'}
          </p>
        </div>

        {/* Recommendation Banner */}
        {hasRecommendation && (
          <div className={`border-2 rounded-lg p-4 mb-6 ${
            detectionResult.recommended_strategy === DeploymentStrategy.CLEAN_DEPLOY
              ? 'bg-yellow-50 border-yellow-400'
              : 'bg-green-50 border-green-400'
          }`}>
            <div className="flex items-start">
              <svg className={`w-6 h-6 mr-3 flex-shrink-0 ${
                detectionResult.recommended_strategy === DeploymentStrategy.CLEAN_DEPLOY
                  ? 'text-yellow-600'
                  : 'text-green-600'
              }`} fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
              </svg>
              <div className="flex-1">
                <h3 className={`font-bold mb-1 ${
                  detectionResult.recommended_strategy === DeploymentStrategy.CLEAN_DEPLOY
                    ? 'text-yellow-900'
                    : 'text-green-900'
                }`}>
                  Recommended Strategy: {detectionResult.recommended_strategy === DeploymentStrategy.CLEAN_DEPLOY ? 'Clean and Redeploy' : 'Update Existing'}
                </h3>
                <p className={`text-sm ${
                  detectionResult.recommended_strategy === DeploymentStrategy.CLEAN_DEPLOY
                    ? 'text-yellow-800'
                    : 'text-green-800'
                }`}>
                  {detectionResult.recommendation_reason}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Wait for in-progress operations */}
        {detectionResult.has_in_progress_stacks && (
          <div className="bg-blue-50 border-2 border-blue-400 rounded-lg p-4 mb-6">
            <div className="flex items-start">
              <svg className="w-6 h-6 text-blue-600 mr-3 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clipRule="evenodd" />
              </svg>
              <div>
                <h4 className="font-semibold text-blue-900 mb-2">Operations In Progress</h4>
                <p className="text-blue-800 text-sm mb-2">
                  Some stacks have operations in progress. Please wait for them to complete before deploying.
                </p>
                <ul className="text-sm text-blue-700 space-y-1">
                  {detectionResult.stacks_found
                    .filter(stack => stack.classification === 'in_progress')
                    .map(stack => (
                      <li key={stack.stack_name} className="flex items-center">
                        <span className="font-mono text-xs bg-blue-100 px-2 py-1 rounded mr-2">
                          {stack.stack_type}
                        </span>
                        <span>{stack.stack_status}</span>
                      </li>
                    ))}
                </ul>
              </div>
            </div>
          </div>
        )}

        {/* Detection Summary */}
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
          <h3 className="font-semibold text-blue-900 mb-2">Installation Details</h3>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-blue-700 font-medium">Capability:</span>
              <span className="ml-2 text-blue-900">{detectionResult.capability_name}</span>
            </div>
            <div>
              <span className="text-blue-700 font-medium">Environment:</span>
              <span className="ml-2 text-blue-900">{detectionResult.environment}</span>
            </div>
            <div>
              <span className="text-blue-700 font-medium">Region:</span>
              <span className="ml-2 text-blue-900">{detectionResult.region}</span>
            </div>
            <div>
              <span className="text-blue-700 font-medium">Stacks Found:</span>
              <span className="ml-2 text-blue-900">{detectionResult.stacks_found.length}</span>
            </div>
          </div>
        </div>

        {/* Failed Stacks Warning */}
        {detectionResult.has_failed_stacks && (
          <div className="bg-yellow-50 border border-yellow-300 rounded-lg p-4 mb-6">
            <div className="flex items-start">
              <svg className="w-6 h-6 text-yellow-600 mr-3 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
              </svg>
              <div>
                <h4 className="font-semibold text-yellow-900 mb-2">Failed Stacks Detected</h4>
                <p className="text-yellow-800 text-sm mb-2">
                  Some stacks are in a failed state and cannot be updated. You must use "Clean and Redeploy" to remove them.
                </p>
                <ul className="text-sm text-yellow-700 space-y-1">
                  {detectionResult.stacks_found
                    .filter(stack => stack.classification === 'failed')
                    .map(stack => (
                      <li key={stack.stack_name} className="flex items-center">
                        <span className="font-mono text-xs bg-yellow-100 px-2 py-1 rounded mr-2">
                          {stack.stack_type}
                        </span>
                        <span>{stack.stack_status}</span>
                        {stack.status_reason && (
                          <span className="ml-2 text-xs text-yellow-600">- {stack.status_reason}</span>
                        )}
                      </li>
                    ))}
                </ul>
              </div>
            </div>
          </div>
        )}

        {/* Stack States Table */}
        {detectionResult.stacks_found.length > 0 && (
          <div className="mb-6">
            <h3 className="font-semibold text-gray-900 mb-3">Detected Stacks</h3>
            <div className="border border-gray-300 rounded-lg overflow-hidden">
              <table className="min-w-full divide-y divide-gray-300">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Stack Type
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Status
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Region
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Classification
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {detectionResult.stacks_found.map(stack => (
                    <tr key={stack.stack_name} className={
                      stack.classification === 'failed' ? 'bg-red-50' :
                      stack.classification === 'in_progress' ? 'bg-yellow-50' :
                      'bg-green-50'
                    }>
                      <td className="px-4 py-3 text-sm font-medium text-gray-900">
                        {stack.stack_type}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-700">
                        <div className="flex flex-col">
                          <span>{stack.stack_status}</span>
                          {stack.status_reason && (
                            <span className="text-xs text-gray-500 mt-1">{stack.status_reason}</span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-700">
                        {stack.region}
                      </td>
                      <td className="px-4 py-3 text-sm">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                          stack.classification === 'updatable' ? 'bg-green-100 text-green-800' :
                          stack.classification === 'failed' ? 'bg-red-100 text-red-800' :
                          'bg-yellow-100 text-yellow-800'
                        }`}>
                          {stack.classification}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Strategy Options */}
        <div className="space-y-4 mb-6">
          {/* Clean and Redeploy Option */}
          <div
            className={`border-2 rounded-lg p-4 cursor-pointer transition-all ${
              selectedStrategy === DeploymentStrategy.CLEAN_DEPLOY
                ? 'border-red-500 bg-red-50'
                : 'border-gray-300 hover:border-red-300 hover:bg-red-50'
            }`}
            onClick={() => setSelectedStrategy(DeploymentStrategy.CLEAN_DEPLOY)}
          >
            <div className="flex items-start">
              <input
                type="radio"
                checked={selectedStrategy === DeploymentStrategy.CLEAN_DEPLOY}
                onChange={() => setSelectedStrategy(DeploymentStrategy.CLEAN_DEPLOY)}
                className="mt-1 mr-3"
              />
              <div className="flex-1">
                <div className="flex items-center mb-2">
                  <svg className="w-5 h-5 text-red-600 mr-2" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clipRule="evenodd" />
                  </svg>
                  <h3 className="text-lg font-semibold text-gray-900">Clean and Redeploy</h3>
                </div>
                <p className="text-gray-700 mb-2">
                  Delete all existing stacks and deploy fresh infrastructure from scratch.
                </p>
                <div className="bg-red-100 border border-red-300 rounded p-3 text-sm">
                  <p className="font-semibold text-red-900 mb-1">⚠️ Warning: Data Loss</p>
                  <p className="text-red-800">
                    All existing resources will be permanently deleted, including databases, S3 buckets, and configurations.
                    This action cannot be undone.
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* Update Existing Option */}
          <div
            className={`border-2 rounded-lg p-4 transition-all ${
              !canUpdate
                ? 'border-gray-200 bg-gray-50 opacity-60 cursor-not-allowed'
                : selectedStrategy === DeploymentStrategy.UPDATE_EXISTING
                ? 'border-green-500 bg-green-50 cursor-pointer'
                : 'border-gray-300 hover:border-green-300 hover:bg-green-50 cursor-pointer'
            }`}
            onClick={() => canUpdate && setSelectedStrategy(DeploymentStrategy.UPDATE_EXISTING)}
          >
            <div className="flex items-start">
              <input
                type="radio"
                checked={selectedStrategy === DeploymentStrategy.UPDATE_EXISTING}
                onChange={() => canUpdate && setSelectedStrategy(DeploymentStrategy.UPDATE_EXISTING)}
                disabled={!canUpdate}
                className="mt-1 mr-3"
              />
              <div className="flex-1">
                <div className="flex items-center mb-2">
                  <svg className="w-5 h-5 text-green-600 mr-2" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clipRule="evenodd" />
                  </svg>
                  <h3 className="text-lg font-semibold text-gray-900">Update Existing</h3>
                  {!canUpdate && (
                    <span className="ml-2 text-xs bg-gray-200 text-gray-700 px-2 py-1 rounded">
                      Not Available
                    </span>
                  )}
                </div>
                <p className="text-gray-700 mb-2">
                  Update existing stacks in place, preserving data and configurations where possible.
                </p>
                <div className="bg-green-100 border border-green-300 rounded p-3 text-sm">
                  <p className="font-semibold text-green-900 mb-1">✓ Data Preservation</p>
                  <p className="text-green-800">
                    Existing resources will be updated without deletion. Databases, S3 buckets, and configurations
                    will be preserved. Minimal downtime expected.
                  </p>
                </div>
                {!canUpdate && (
                  <div className="mt-2 text-sm text-gray-600">
                    <p>This option is unavailable because stacks are in a failed state. Please use "Clean and Redeploy".</p>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Update Options Panel - shown when Update Existing is selected */}
          {selectedStrategy === DeploymentStrategy.UPDATE_EXISTING && canUpdate && (
            <div className="mt-4 ml-8">
              <UpdateOptionsPanel
                stacks={detectionResult.stacks_found}
                onOptionsChange={handleUpdateOptionsChange}
                initialOptions={updateOptions}
                driftResult={driftResult}
                isLoadingDrift={isLoadingDrift}
                onDetectDrift={onDetectDrift ? handleDetectDrift : undefined}
              />
            </div>
          )}
        </div>

        {/* Complete Cleanup Option */}
        {onCompleteCleanup && (
          <div className="mt-6 pt-6 border-t border-gray-300">
            <div className="bg-red-50 border-2 border-red-300 rounded-lg p-4">
              <div className="flex items-start">
                <svg className="w-6 h-6 text-red-600 mr-3 flex-shrink-0 mt-1" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                </svg>
                <div className="flex-1">
                  <h3 className="text-lg font-bold text-red-900 mb-2">
                    🚨 Nuclear Option: Complete Cleanup
                  </h3>
                  <p className="text-red-800 text-sm mb-3">
                    If deployments keep failing due to stuck resources, use this option to forcefully remove 
                    <strong> ALL resources</strong> including stacks, S3 buckets, ECR repositories, log groups, 
                    and state files. This is more aggressive than "Clean and Redeploy".
                  </p>
                  <div className="bg-red-100 border border-red-400 rounded p-3 mb-3 text-sm">
                    <p className="font-bold text-red-900 mb-1">⚠️ EXTREME WARNING</p>
                    <ul className="text-red-800 space-y-1 ml-4 list-disc">
                      <li>Removes ALL resources, even those not managed by CloudFormation</li>
                      <li>Deletes all data permanently - cannot be recovered</li>
                      <li>Disables termination protection automatically</li>
                      <li>May take several minutes to complete</li>
                      <li>Use only when normal cleanup fails repeatedly</li>
                    </ul>
                  </div>
                  {!showCleanupConfirm ? (
                    <button
                      onClick={() => setShowCleanupConfirm(true)}
                      className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors font-semibold text-sm"
                    >
                      🧹 Initiate Complete Cleanup
                    </button>
                  ) : (
                    <div className="space-y-2">
                      <p className="font-bold text-red-900 text-sm">
                        Are you absolutely sure? This action cannot be undone!
                      </p>
                      <div className="flex gap-2">
                        <button
                          onClick={handleCompleteCleanup}
                          className="px-4 py-2 bg-red-700 text-white rounded-lg hover:bg-red-800 transition-colors font-bold text-sm"
                        >
                          ✓ Yes, Delete Everything
                        </button>
                        <button
                          onClick={() => setShowCleanupConfirm(false)}
                          className="px-4 py-2 bg-gray-300 text-gray-700 rounded-lg hover:bg-gray-400 transition-colors text-sm"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Action Buttons */}
        <div className="flex justify-between pt-4 border-t">
          <button
            onClick={onCancel}
            className="px-6 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 transition-colors"
          >
            ← Back
          </button>
          <button
            onClick={handleContinue}
            disabled={!selectedStrategy}
            className={`px-6 py-2 rounded-lg font-semibold transition-colors ${
              selectedStrategy
                ? 'bg-blue-600 text-white hover:bg-blue-700'
                : 'bg-gray-300 text-gray-500 cursor-not-allowed'
            }`}
          >
            Continue →
          </button>
        </div>
      </div>
    </div>
  );
};
