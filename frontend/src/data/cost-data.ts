/**
 * Cost Estimation Data
 * Estimated monthly costs for AWS resources by environment
 */

export interface CostEstimate {
  resource: string;
  description: string;
  monthlyCostMin: number;
  monthlyCostMax: number;
  pricingLink: string;
  isOptional?: boolean;
}

export interface EnvironmentCosts {
  dev: CostEstimate[];
  stage: CostEstimate[];
  prod: CostEstimate[];
}

export const COST_ESTIMATES: EnvironmentCosts = {
  dev: [
    {
      resource: 'NAT Gateway',
      description: 'Network address translation for private subnets (optional)',
      monthlyCostMin: 45,
      monthlyCostMax: 50,
      pricingLink: 'https://aws.amazon.com/vpc/pricing/',
      isOptional: true
    },
    {
      resource: 'Application Load Balancer',
      description: 'Load balancing for ECS services',
      monthlyCostMin: 18,
      monthlyCostMax: 25,
      pricingLink: 'https://aws.amazon.com/elasticloadbalancing/pricing/'
    },
    {
      resource: 'ECS Fargate',
      description: 'Container compute (0.5 vCPU, 1GB memory)',
      monthlyCostMin: 15,
      monthlyCostMax: 30,
      pricingLink: 'https://aws.amazon.com/fargate/pricing/'
    },
    {
      resource: 'CloudFront',
      description: 'CDN data transfer (estimated 10-50GB/month)',
      monthlyCostMin: 5,
      monthlyCostMax: 20,
      pricingLink: 'https://aws.amazon.com/cloudfront/pricing/'
    },
    {
      resource: 'DynamoDB',
      description: 'On-demand capacity (low traffic)',
      monthlyCostMin: 1,
      monthlyCostMax: 10,
      pricingLink: 'https://aws.amazon.com/dynamodb/pricing/'
    },
    {
      resource: 'S3',
      description: 'Storage and requests (estimated 1-5GB)',
      monthlyCostMin: 1,
      monthlyCostMax: 5,
      pricingLink: 'https://aws.amazon.com/s3/pricing/'
    },
    {
      resource: 'CloudWatch',
      description: 'Logs, metrics, and alarms',
      monthlyCostMin: 5,
      monthlyCostMax: 15,
      pricingLink: 'https://aws.amazon.com/cloudwatch/pricing/'
    },
    {
      resource: 'Secrets Manager',
      description: 'Secret storage (per secret/month)',
      monthlyCostMin: 1,
      monthlyCostMax: 5,
      pricingLink: 'https://aws.amazon.com/secrets-manager/pricing/'
    }
  ],
  stage: [
    {
      resource: 'NAT Gateway',
      description: 'Network address translation for private subnets (optional)',
      monthlyCostMin: 45,
      monthlyCostMax: 60,
      pricingLink: 'https://aws.amazon.com/vpc/pricing/',
      isOptional: true
    },
    {
      resource: 'Application Load Balancer',
      description: 'Load balancing for ECS services',
      monthlyCostMin: 20,
      monthlyCostMax: 35,
      pricingLink: 'https://aws.amazon.com/elasticloadbalancing/pricing/'
    },
    {
      resource: 'ECS Fargate',
      description: 'Container compute (1 vCPU, 2GB memory, 2 tasks)',
      monthlyCostMin: 40,
      monthlyCostMax: 80,
      pricingLink: 'https://aws.amazon.com/fargate/pricing/'
    },
    {
      resource: 'CloudFront',
      description: 'CDN data transfer (estimated 50-200GB/month)',
      monthlyCostMin: 15,
      monthlyCostMax: 40,
      pricingLink: 'https://aws.amazon.com/cloudfront/pricing/'
    },
    {
      resource: 'DynamoDB',
      description: 'On-demand capacity (moderate traffic)',
      monthlyCostMin: 5,
      monthlyCostMax: 25,
      pricingLink: 'https://aws.amazon.com/dynamodb/pricing/'
    },
    {
      resource: 'S3',
      description: 'Storage and requests (estimated 5-20GB)',
      monthlyCostMin: 2,
      monthlyCostMax: 10,
      pricingLink: 'https://aws.amazon.com/s3/pricing/'
    },
    {
      resource: 'CloudWatch',
      description: 'Logs, metrics, and alarms',
      monthlyCostMin: 10,
      monthlyCostMax: 30,
      pricingLink: 'https://aws.amazon.com/cloudwatch/pricing/'
    },
    {
      resource: 'Secrets Manager',
      description: 'Secret storage (per secret/month)',
      monthlyCostMin: 2,
      monthlyCostMax: 8,
      pricingLink: 'https://aws.amazon.com/secrets-manager/pricing/'
    }
  ],
  prod: [
    {
      resource: 'NAT Gateway',
      description: 'Network address translation for private subnets (recommended for production)',
      monthlyCostMin: 90,
      monthlyCostMax: 150,
      pricingLink: 'https://aws.amazon.com/vpc/pricing/',
      isOptional: true
    },
    {
      resource: 'Application Load Balancer',
      description: 'Load balancing for ECS services (multi-AZ)',
      monthlyCostMin: 25,
      monthlyCostMax: 50,
      pricingLink: 'https://aws.amazon.com/elasticloadbalancing/pricing/'
    },
    {
      resource: 'ECS Fargate',
      description: 'Container compute (2 vCPU, 4GB memory, 3+ tasks)',
      monthlyCostMin: 100,
      monthlyCostMax: 250,
      pricingLink: 'https://aws.amazon.com/fargate/pricing/'
    },
    {
      resource: 'CloudFront',
      description: 'CDN data transfer (estimated 500GB-2TB/month)',
      monthlyCostMin: 50,
      monthlyCostMax: 150,
      pricingLink: 'https://aws.amazon.com/cloudfront/pricing/'
    },
    {
      resource: 'DynamoDB',
      description: 'On-demand capacity (production traffic)',
      monthlyCostMin: 25,
      monthlyCostMax: 100,
      pricingLink: 'https://aws.amazon.com/dynamodb/pricing/'
    },
    {
      resource: 'S3',
      description: 'Storage and requests (estimated 50-200GB)',
      monthlyCostMin: 5,
      monthlyCostMax: 25,
      pricingLink: 'https://aws.amazon.com/s3/pricing/'
    },
    {
      resource: 'CloudWatch',
      description: 'Logs, metrics, and alarms (extended retention)',
      monthlyCostMin: 25,
      monthlyCostMax: 75,
      pricingLink: 'https://aws.amazon.com/cloudwatch/pricing/'
    },
    {
      resource: 'Secrets Manager',
      description: 'Secret storage (per secret/month)',
      monthlyCostMin: 5,
      monthlyCostMax: 15,
      pricingLink: 'https://aws.amazon.com/secrets-manager/pricing/'
    },
    {
      resource: 'WAF',
      description: 'Web Application Firewall rules',
      monthlyCostMin: 10,
      monthlyCostMax: 30,
      pricingLink: 'https://aws.amazon.com/waf/pricing/'
    }
  ]
};

export interface CostSummary {
  min: number;
  max: number;
  breakdown: CostEstimate[];
}

/**
 * Calculate total estimated cost for an environment
 * @param environment - The deployment environment (dev, stage, prod)
 * @param enableNATGateway - Whether NAT Gateway is enabled
 * @returns Cost summary with min/max totals and breakdown
 */
export function calculateTotalCost(
  environment: 'dev' | 'stage' | 'prod',
  enableNATGateway: boolean = false
): CostSummary {
  const estimates = COST_ESTIMATES[environment] || COST_ESTIMATES.dev;
  let min = 0;
  let max = 0;
  const breakdown: CostEstimate[] = [];

  for (const estimate of estimates) {
    // Skip NAT Gateway if not enabled
    if (estimate.resource === 'NAT Gateway' && !enableNATGateway) {
      continue;
    }
    min += estimate.monthlyCostMin;
    max += estimate.monthlyCostMax;
    breakdown.push(estimate);
  }

  return { min, max, breakdown };
}

/**
 * Format cost as currency string
 */
export function formatCost(amount: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0
  }).format(amount);
}

/**
 * Get cost comparison between environments
 */
export function getEnvironmentCostComparison(): {
  environment: string;
  minCost: number;
  maxCost: number;
}[] {
  return [
    { environment: 'dev', ...calculateTotalCost('dev', false) },
    { environment: 'stage', ...calculateTotalCost('stage', false) },
    { environment: 'prod', ...calculateTotalCost('prod', true) }
  ].map(({ environment, min, max }) => ({
    environment,
    minCost: min,
    maxCost: max
  }));
}
