/**
 * Cost Estimation Panel Component
 * Displays estimated monthly costs for the deployment
 */
import React, { useState, useMemo } from 'react';
import { calculateTotalCost, formatCost, CostEstimate } from '../data/cost-data';

interface CostEstimationPanelProps {
  environment: 'dev' | 'stage' | 'prod';
  enableNATGateway?: boolean;
}

const CostEstimationPanel: React.FC<CostEstimationPanelProps> = ({
  environment,
  enableNATGateway = false
}) => {
  const [expanded, setExpanded] = useState(false);

  const costSummary = useMemo(() => {
    return calculateTotalCost(environment, enableNATGateway);
  }, [environment, enableNATGateway]);

  const environmentLabels: Record<string, string> = {
    dev: 'Development',
    stage: 'Staging',
    prod: 'Production'
  };

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-4 py-3 bg-gray-50 hover:bg-gray-100 flex items-center justify-between transition-colors"
        aria-expanded={expanded}
      >
        <div className="flex items-center">
          <svg
            className={`w-5 h-5 text-gray-500 mr-2 transition-transform ${expanded ? 'rotate-90' : ''}`}
            fill="currentColor"
            viewBox="0 0 20 20"
          >
            <path
              fillRule="evenodd"
              d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z"
              clipRule="evenodd"
            />
          </svg>
          <span className="font-medium text-gray-900">Estimated Monthly Cost</span>
        </div>
        <div className="flex items-center">
          <span className="text-lg font-semibold text-green-600">
            {formatCost(costSummary.min)} - {formatCost(costSummary.max)}
          </span>
          <span className="ml-2 text-sm text-gray-500">/month</span>
        </div>
      </button>

      {/* Expanded Content */}
      {expanded && (
        <div className="p-4 border-t border-gray-200">
          {/* Environment Badge */}
          <div className="mb-4 flex items-center justify-between">
            <div className="flex items-center">
              <span className={`px-3 py-1 rounded-full text-sm font-medium ${
                environment === 'prod' 
                  ? 'bg-red-100 text-red-800' 
                  : environment === 'stage'
                  ? 'bg-yellow-100 text-yellow-800'
                  : 'bg-green-100 text-green-800'
              }`}>
                {environmentLabels[environment]} Environment
              </span>
              {enableNATGateway && (
                <span className="ml-2 px-2 py-1 bg-blue-100 text-blue-800 text-xs rounded-full">
                  NAT Gateway Enabled
                </span>
              )}
            </div>
          </div>

          {/* Cost Breakdown Table */}
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Resource
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Description
                  </th>
                  <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Est. Cost/Month
                  </th>
                  <th className="px-4 py-2 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Pricing
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {costSummary.breakdown.map((item) => (
                  <CostRow key={item.resource} item={item} />
                ))}
              </tbody>
              <tfoot className="bg-gray-50">
                <tr>
                  <td colSpan={2} className="px-4 py-3 text-sm font-medium text-gray-900">
                    Estimated Total
                  </td>
                  <td className="px-4 py-3 text-right text-sm font-semibold text-green-600">
                    {formatCost(costSummary.min)} - {formatCost(costSummary.max)}
                  </td>
                  <td></td>
                </tr>
              </tfoot>
            </table>
          </div>

          {/* NAT Gateway Note */}
          {!enableNATGateway && (
            <div className="mt-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
              <div className="flex items-start">
                <svg className="w-5 h-5 text-blue-600 mr-2 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
                </svg>
                <div className="text-sm text-blue-800">
                  <p className="font-medium">NAT Gateway Not Included</p>
                  <p className="mt-1">
                    NAT Gateway costs ~$45-150/month depending on usage. Enable it in Infrastructure Configuration 
                    if your backend needs to access external APIs from private subnets.
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Disclaimer */}
          <div className="mt-4 p-3 bg-gray-50 border border-gray-200 rounded-lg">
            <p className="text-xs text-gray-600">
              <strong>Disclaimer:</strong> These are estimated costs based on typical usage patterns. 
              Actual costs may vary based on data transfer, request volumes, and regional pricing. 
              Use the <a href="https://calculator.aws/" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">AWS Pricing Calculator</a> for 
              more accurate estimates.
            </p>
          </div>
        </div>
      )}
    </div>
  );
};

interface CostRowProps {
  item: CostEstimate;
}

const CostRow: React.FC<CostRowProps> = ({ item }) => {
  return (
    <tr className={item.isOptional ? 'bg-blue-50' : ''}>
      <td className="px-4 py-3 whitespace-nowrap">
        <div className="flex items-center">
          <span className="text-sm font-medium text-gray-900">{item.resource}</span>
          {item.isOptional && (
            <span className="ml-2 px-1.5 py-0.5 bg-blue-100 text-blue-700 text-xs rounded">
              Optional
            </span>
          )}
        </div>
      </td>
      <td className="px-4 py-3">
        <span className="text-sm text-gray-600">{item.description}</span>
      </td>
      <td className="px-4 py-3 text-right whitespace-nowrap">
        <span className="text-sm text-gray-900">
          {formatCost(item.monthlyCostMin)} - {formatCost(item.monthlyCostMax)}
        </span>
      </td>
      <td className="px-4 py-3 text-center">
        <a
          href={item.pricingLink}
          target="_blank"
          rel="noopener noreferrer"
          className="text-blue-600 hover:text-blue-800"
          title="View AWS Pricing"
        >
          <svg className="w-4 h-4 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
          </svg>
        </a>
      </td>
    </tr>
  );
};

export default CostEstimationPanel;
