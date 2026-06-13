/**
 * Error Help Data
 * Contextual help for permission verification errors
 */

export type ErrorType = 
  | 'AccessDenied'
  | 'InvalidRoleArn'
  | 'ExpiredCredentials'
  | 'InsufficientPermissions'
  | 'CrossAccountTrustFailure'
  | 'NetworkError'
  | 'RateLimitExceeded'
  | 'InvalidExternalId'
  | 'MalformedPolicy'
  | 'ServiceUnavailable';

export interface RemediationStep {
  step: number;
  instruction: string;
  command?: string;
  link?: string;
}

export interface ErrorHelp {
  type: ErrorType;
  title: string;
  description: string;
  remediation: RemediationStep[];
}

export const ERROR_HELP_DATA: Record<ErrorType, ErrorHelp> = {
  AccessDenied: {
    type: 'AccessDenied',
    title: 'Access Denied',
    description: 'Unable to assume the specified IAM role. The trust policy may not allow access from your account.',
    remediation: [
      {
        step: 1,
        instruction: 'Verify the role ARN is correct and the role exists',
        command: 'aws iam get-role --role-name YOUR_ROLE_NAME'
      },
      {
        step: 2,
        instruction: 'Check the trust policy allows your account to assume the role',
        link: 'https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_permissions-to-switch.html'
      },
      {
        step: 3,
        instruction: 'If using external ID, ensure it matches exactly'
      },
      {
        step: 4,
        instruction: 'Verify your current credentials have sts:AssumeRole permission'
      }
    ]
  },
  InvalidRoleArn: {
    type: 'InvalidRoleArn',
    title: 'Invalid Role ARN',
    description: 'The provided Role ARN format is invalid. ARNs must follow the AWS ARN format.',
    remediation: [
      {
        step: 1,
        instruction: 'Verify the ARN format: arn:aws:iam::ACCOUNT_ID:role/ROLE_NAME'
      },
      {
        step: 2,
        instruction: 'Check for typos in the account ID (must be 12 digits)'
      },
      {
        step: 3,
        instruction: 'Ensure the role name does not contain invalid characters'
      },
      {
        step: 4,
        instruction: 'Copy the ARN directly from the IAM console to avoid errors',
        link: 'https://console.aws.amazon.com/iam/home#/roles'
      }
    ]
  },
  ExpiredCredentials: {
    type: 'ExpiredCredentials',
    title: 'Expired Credentials',
    description: 'Your AWS session has expired. Temporary credentials have a limited lifetime.',
    remediation: [
      {
        step: 1,
        instruction: 'Re-authenticate using your preferred method'
      },
      {
        step: 2,
        instruction: 'For ADFS/SSO, log in again to get fresh credentials'
      },
      {
        step: 3,
        instruction: 'For access keys, verify they are still active in IAM console'
      },
      {
        step: 4,
        instruction: 'Check if MFA is required and provide a new token if needed'
      }
    ]
  },
  InsufficientPermissions: {
    type: 'InsufficientPermissions',
    title: 'Insufficient Permissions',
    description: 'The IAM role lacks one or more required permissions for deployment.',
    remediation: [
      {
        step: 1,
        instruction: 'Download the required IAM policy from the wizard'
      },
      {
        step: 2,
        instruction: 'Attach the policy to your deployment role',
        command: 'aws iam put-role-policy --role-name YOUR_ROLE --policy-name Nexus AIDeployment --policy-document file://policy.json'
      },
      {
        step: 3,
        instruction: 'Wait a few seconds for IAM changes to propagate'
      },
      {
        step: 4,
        instruction: 'Re-run the permission verification'
      }
    ]
  },
  CrossAccountTrustFailure: {
    type: 'CrossAccountTrustFailure',
    title: 'Cross-Account Trust Not Configured',
    description: 'The target account role does not trust the source account for cross-account access.',
    remediation: [
      {
        step: 1,
        instruction: 'Update the trust policy on the target role to include your source account'
      },
      {
        step: 2,
        instruction: 'Add the source account ID to the Principal in the trust policy'
      },
      {
        step: 3,
        instruction: 'Configure an external ID for additional security',
        link: 'https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_create_for-user_externalid.html'
      },
      {
        step: 4,
        instruction: 'Use the Setup Guide in the wizard for detailed instructions'
      }
    ]
  },
  NetworkError: {
    type: 'NetworkError',
    title: 'Network Connection Error',
    description: 'Unable to connect to AWS services. Check your network connectivity.',
    remediation: [
      {
        step: 1,
        instruction: 'Verify your internet connection is working'
      },
      {
        step: 2,
        instruction: 'Check if a firewall or proxy is blocking AWS endpoints'
      },
      {
        step: 3,
        instruction: 'Try accessing AWS console in your browser to verify connectivity',
        link: 'https://console.aws.amazon.com'
      },
      {
        step: 4,
        instruction: 'If using VPN, ensure AWS endpoints are accessible'
      }
    ]
  },
  RateLimitExceeded: {
    type: 'RateLimitExceeded',
    title: 'Rate Limit Exceeded',
    description: 'Too many API requests. AWS has temporarily throttled your requests.',
    remediation: [
      {
        step: 1,
        instruction: 'Wait a few minutes before retrying'
      },
      {
        step: 2,
        instruction: 'Reduce the frequency of API calls if running automated scripts'
      },
      {
        step: 3,
        instruction: 'Consider requesting a service limit increase if this persists',
        link: 'https://docs.aws.amazon.com/servicequotas/latest/userguide/request-quota-increase.html'
      }
    ]
  },
  InvalidExternalId: {
    type: 'InvalidExternalId',
    title: 'Invalid External ID',
    description: 'The external ID provided does not match the one configured in the trust policy.',
    remediation: [
      {
        step: 1,
        instruction: 'Verify the external ID matches exactly (case-sensitive)'
      },
      {
        step: 2,
        instruction: 'Check the trust policy condition for the expected external ID'
      },
      {
        step: 3,
        instruction: 'Update either the trust policy or the external ID you are using'
      }
    ]
  },
  MalformedPolicy: {
    type: 'MalformedPolicy',
    title: 'Malformed IAM Policy',
    description: 'The IAM policy attached to the role contains syntax errors.',
    remediation: [
      {
        step: 1,
        instruction: 'Validate the policy JSON syntax'
      },
      {
        step: 2,
        instruction: 'Use the IAM policy validator in AWS console',
        link: 'https://console.aws.amazon.com/iam/home#/policies'
      },
      {
        step: 3,
        instruction: 'Download a fresh policy from the wizard and re-apply'
      }
    ]
  },
  ServiceUnavailable: {
    type: 'ServiceUnavailable',
    title: 'AWS Service Unavailable',
    description: 'One or more AWS services are temporarily unavailable.',
    remediation: [
      {
        step: 1,
        instruction: 'Check AWS Service Health Dashboard',
        link: 'https://health.aws.amazon.com/health/status'
      },
      {
        step: 2,
        instruction: 'Wait a few minutes and retry'
      },
      {
        step: 3,
        instruction: 'Try a different AWS region if the issue persists'
      }
    ]
  }
};

/**
 * Get error help for a specific error type
 */
export function getErrorHelp(errorType: ErrorType): ErrorHelp {
  return ERROR_HELP_DATA[errorType];
}

/**
 * Get all error types
 */
export function getAllErrorTypes(): ErrorType[] {
  return Object.keys(ERROR_HELP_DATA) as ErrorType[];
}

/**
 * Match an error message to an error type
 */
export function matchErrorType(errorMessage: string): ErrorType | null {
  const lowerMessage = errorMessage.toLowerCase();
  
  if (lowerMessage.includes('access denied') || lowerMessage.includes('not authorized')) {
    return 'AccessDenied';
  }
  if (lowerMessage.includes('invalid arn') || lowerMessage.includes('malformed arn')) {
    return 'InvalidRoleArn';
  }
  if (lowerMessage.includes('expired') || lowerMessage.includes('token has expired')) {
    return 'ExpiredCredentials';
  }
  if (lowerMessage.includes('insufficient') || lowerMessage.includes('missing permission')) {
    return 'InsufficientPermissions';
  }
  if (lowerMessage.includes('trust') || lowerMessage.includes('cross-account')) {
    return 'CrossAccountTrustFailure';
  }
  if (lowerMessage.includes('network') || lowerMessage.includes('connection') || lowerMessage.includes('timeout') || lowerMessage.includes('connect')) {
    return 'NetworkError';
  }
  if (lowerMessage.includes('throttl') || lowerMessage.includes('rate limit') || lowerMessage.includes('too many')) {
    return 'RateLimitExceeded';
  }
  if (lowerMessage.includes('external id')) {
    return 'InvalidExternalId';
  }
  if (lowerMessage.includes('malformed') || lowerMessage.includes('syntax')) {
    return 'MalformedPolicy';
  }
  if (lowerMessage.includes('unavailable') || lowerMessage.includes('service error')) {
    return 'ServiceUnavailable';
  }
  
  return null;
}
