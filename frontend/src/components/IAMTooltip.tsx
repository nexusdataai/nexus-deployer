/**
 * IAM Tooltip Component
 * Contextual help tooltips for IAM-related fields
 */
import React, { useState, useRef, useEffect } from 'react';

type TooltipField = 'roleArn' | 'region' | 'externalId' | 'accountId';
type TooltipPlacement = 'top' | 'bottom' | 'left' | 'right';

interface TooltipContent {
  title: string;
  description: string;
  example?: string;
  learnMoreLink?: string;
}

const TOOLTIP_CONTENT: Record<TooltipField, TooltipContent> = {
  roleArn: {
    title: 'IAM Role ARN',
    description: 'The Amazon Resource Name (ARN) of the IAM role that will be assumed for deployment.',
    example: 'arn:aws:iam::123456789012:role/MyDeploymentRole',
    learnMoreLink: 'https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_identifiers.html#identifiers-arns'
  },
  region: {
    title: 'AWS Region',
    description: 'The AWS region where resources will be deployed. Choose a region close to your users.',
    example: 'us-east-1, eu-west-1, ap-southeast-1',
    learnMoreLink: 'https://docs.aws.amazon.com/general/latest/gr/rande.html'
  },
  externalId: {
    title: 'External ID',
    description: 'A unique identifier used for cross-account access to prevent confused deputy attacks.',
    example: 'nexus-deployment-abc123',
    learnMoreLink: 'https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_create_for-user_externalid.html'
  },
  accountId: {
    title: 'AWS Account ID',
    description: 'The 12-digit AWS account identifier where resources will be deployed.',
    example: '123456789012',
    learnMoreLink: 'https://docs.aws.amazon.com/general/latest/gr/acct-identifiers.html'
  }
};


interface IAMTooltipProps {
  field: TooltipField;
  placement?: TooltipPlacement;
  children: React.ReactNode;
}

const IAMTooltip: React.FC<IAMTooltipProps> = ({
  field,
  placement = 'top',
  children
}) => {
  const [isVisible, setIsVisible] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const triggerRef = useRef<HTMLDivElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);

  const content = TOOLTIP_CONTENT[field];

  useEffect(() => {
    if (isVisible && triggerRef.current && tooltipRef.current) {
      const triggerRect = triggerRef.current.getBoundingClientRect();
      const tooltipRect = tooltipRef.current.getBoundingClientRect();
      
      let top = 0;
      let left = 0;

      switch (placement) {
        case 'top':
          top = -tooltipRect.height - 8;
          left = (triggerRect.width - tooltipRect.width) / 2;
          break;
        case 'bottom':
          top = triggerRect.height + 8;
          left = (triggerRect.width - tooltipRect.width) / 2;
          break;
        case 'left':
          top = (triggerRect.height - tooltipRect.height) / 2;
          left = -tooltipRect.width - 8;
          break;
        case 'right':
          top = (triggerRect.height - tooltipRect.height) / 2;
          left = triggerRect.width + 8;
          break;
      }

      setPosition({ top, left });
    }
  }, [isVisible, placement]);

  return (
    <div 
      className="relative inline-flex items-center"
      ref={triggerRef}
      onMouseEnter={() => setIsVisible(true)}
      onMouseLeave={() => setIsVisible(false)}
    >
      {children}
      <button
        type="button"
        className="ml-1 text-gray-400 hover:text-gray-600 focus:outline-none"
        aria-label={`Help for ${content.title}`}
      >
        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-8-3a1 1 0 00-.867.5 1 1 0 11-1.731-1A3 3 0 0113 8a3.001 3.001 0 01-2 2.83V11a1 1 0 11-2 0v-1a1 1 0 011-1 1 1 0 100-2zm0 8a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
        </svg>
      </button>

      {isVisible && (
        <div
          ref={tooltipRef}
          className="absolute z-50 w-72 p-3 bg-gray-900 text-white rounded-lg shadow-lg"
          style={{ top: position.top, left: position.left }}
        >
          <div className="text-sm font-medium mb-1">{content.title}</div>
          <p className="text-xs text-gray-300 mb-2">{content.description}</p>
          {content.example && (
            <div className="mb-2">
              <span className="text-xs text-gray-400">Example: </span>
              <code className="text-xs bg-gray-800 px-1 rounded">{content.example}</code>
            </div>
          )}
          {content.learnMoreLink && (
            <a
              href={content.learnMoreLink}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-blue-400 hover:text-blue-300"
            >
              Learn more →
            </a>
          )}
          {/* Arrow */}
          <div className={`absolute w-2 h-2 bg-gray-900 transform rotate-45 ${
            placement === 'top' ? 'bottom-[-4px] left-1/2 -translate-x-1/2' :
            placement === 'bottom' ? 'top-[-4px] left-1/2 -translate-x-1/2' :
            placement === 'left' ? 'right-[-4px] top-1/2 -translate-y-1/2' :
            'left-[-4px] top-1/2 -translate-y-1/2'
          }`} />
        </div>
      )}
    </div>
  );
};

export default IAMTooltip;
export { TOOLTIP_CONTENT };
export type { TooltipField, TooltipPlacement };
