# IAM Permission Validation Script for Nexus AI Deployment (PowerShell)
# This script checks if the current AWS credentials have all required permissions

param(
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"

# Counters
$script:Passed = 0
$script:Failed = 0
$script:Warnings = 0
$script:FailedServices = @()

function Write-ColorOutput {
    param(
        [string]$Message,
        [string]$Color = "White"
    )
    Write-Host $Message -ForegroundColor $Color
}

function Test-ServiceAccess {
    param(
        [string]$ServiceName,
        [string]$Description,
        [scriptblock]$TestCommand,
        [bool]$IsOptional = $false
    )
    
    try {
        $null = & $TestCommand
        Write-ColorOutput "✓ $ServiceName - $Description" "Green"
        $script:Passed++
        return $true
    }
    catch {
        if ($IsOptional) {
            Write-ColorOutput "⚠ $ServiceName - $Description (may not be required)" "Yellow"
            $script:Warnings++
        }
        else {
            Write-ColorOutput "✗ $ServiceName - $Description" "Red"
            $script:Failed++
            $script:FailedServices += $ServiceName
        }
        return $false
    }
}

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  Nexus AI Deployment Permission Validator" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

# Check if AWS CLI is installed
try {
    $null = Get-Command aws -ErrorAction Stop
}
catch {
    Write-ColorOutput "ERROR: AWS CLI is not installed" "Red"
    Write-Host "Please install AWS CLI: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
    exit 1
}

# Get current identity
Write-Host "Checking AWS credentials..."
try {
    $identity = aws sts get-caller-identity --output json | ConvertFrom-Json
    $AccountId = $identity.Account
    $Arn = $identity.Arn
    Write-ColorOutput "✓ Authenticated as: $Arn" "Green"
    Write-ColorOutput "✓ Account ID: $AccountId" "Green"
}
catch {
    Write-ColorOutput "ERROR: Failed to get AWS identity. Check your credentials." "Red"
    exit 1
}

Write-Host ""
Write-Host "Checking service permissions..."
Write-Host "----------------------------------------------"

# Core Infrastructure
Write-Host ""
Write-Host "Core Infrastructure:" -ForegroundColor Cyan

Test-ServiceAccess -ServiceName "CloudFormation" -Description "Stack management" -TestCommand {
    aws cloudformation list-stacks --max-items 1 --output json 2>$null
}

Test-ServiceAccess -ServiceName "IAM" -Description "Role management" -TestCommand {
    aws iam list-roles --max-items 1 --output json 2>$null
}

# Frontend Services
Write-Host ""
Write-Host "Frontend Services:" -ForegroundColor Cyan

Test-ServiceAccess -ServiceName "S3" -Description "Bucket operations" -TestCommand {
    aws s3 ls --max-items 1 2>$null
}

Test-ServiceAccess -ServiceName "CloudFront" -Description "CDN distribution" -TestCommand {
    aws cloudfront list-distributions --max-items 1 --output json 2>$null
}

Test-ServiceAccess -ServiceName "Route53" -Description "DNS management" -IsOptional $true -TestCommand {
    aws route53 list-hosted-zones --max-items 1 --output json 2>$null
}

Test-ServiceAccess -ServiceName "ACM" -Description "Certificate management" -IsOptional $true -TestCommand {
    aws acm list-certificates --max-items 1 --output json 2>$null
}

Test-ServiceAccess -ServiceName "WAF" -Description "Web application firewall" -IsOptional $true -TestCommand {
    aws wafv2 list-web-acls --scope CLOUDFRONT --region us-east-1 --output json 2>$null
}

# Backend Services
Write-Host ""
Write-Host "Backend Services:" -ForegroundColor Cyan

Test-ServiceAccess -ServiceName "ECS" -Description "Container orchestration" -TestCommand {
    aws ecs list-clusters --max-results 1 --output json 2>$null
}

Test-ServiceAccess -ServiceName "ECR" -Description "Container registry" -TestCommand {
    aws ecr describe-repositories --max-results 1 --output json 2>$null
}

Test-ServiceAccess -ServiceName "EC2/VPC" -Description "VPC and networking" -TestCommand {
    aws ec2 describe-vpcs --max-results 1 --output json 2>$null
}

Test-ServiceAccess -ServiceName "ELB" -Description "Load balancing" -TestCommand {
    aws elbv2 describe-load-balancers --page-size 1 --output json 2>$null
}

# Data Services
Write-Host ""
Write-Host "Data Services:" -ForegroundColor Cyan

Test-ServiceAccess -ServiceName "DynamoDB" -Description "Database tables" -TestCommand {
    aws dynamodb list-tables --max-items 1 --output json 2>$null
}

Test-ServiceAccess -ServiceName "Secrets Manager" -Description "Secrets storage" -TestCommand {
    aws secretsmanager list-secrets --max-results 1 --output json 2>$null
}

Test-ServiceAccess -ServiceName "KMS" -Description "Encryption keys" -TestCommand {
    aws kms list-keys --max-items 1 --output json 2>$null
}

# Monitoring
Write-Host ""
Write-Host "Monitoring Services:" -ForegroundColor Cyan

Test-ServiceAccess -ServiceName "CloudWatch Logs" -Description "Application logging" -TestCommand {
    aws logs describe-log-groups --limit 1 --output json 2>$null
}

# Summary
Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  Summary" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-ColorOutput "Passed: $script:Passed" "Green"
Write-ColorOutput "Failed: $script:Failed" "Red"
Write-ColorOutput "Warnings: $script:Warnings" "Yellow"
Write-Host ""

if ($script:Failed -gt 0) {
    Write-ColorOutput "Some permissions are missing. Please update your IAM policy." "Red"
    Write-Host "Missing access to: $($script:FailedServices -join ', ')"
    Write-Host ""
    Write-Host "Download the required policy from the Nexus AI installer wizard."
    exit 1
}
else {
    Write-ColorOutput "All required permissions are available!" "Green"
    exit 0
}
