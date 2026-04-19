"""
CLI Interface for Call Processing Infrastructure Provisioning.

Provides command-line access to provision, verify, and manage
call-processing infrastructure resources.

Usage:
    python -m app.services.infra_provisioning.cli provision --environment dev
    python -m app.services.infra_provisioning.cli verify --environment prod
    python -m app.services.infra_provisioning.cli dry-run --environment stage
"""

import argparse
import json
import logging
import sys
from dataclasses import asdict
from datetime import datetime
from typing import Optional

from .orchestrator import ProvisioningOrchestrator
from .verification_service import VerificationService
from .models import VALID_ENVIRONMENTS, ResourceStatusType, VerificationStatusType


def setup_logging(verbose: bool = False):
    """Configure logging for CLI output."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def datetime_serializer(obj):
    """JSON serializer for datetime objects."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def format_report_human(report, report_type: str) -> str:
    """Format a report for human-readable output."""
    lines = []
    lines.append("=" * 60)
    lines.append(f"  {report_type.upper()} REPORT")
    lines.append("=" * 60)
    lines.append(f"Environment: {report.environment}")
    lines.append(f"Region: {report.region}")
    
    if hasattr(report, 'dry_run'):
        lines.append(f"Dry Run: {report.dry_run}")
    
    lines.append(f"Started: {report.started_at}")
    lines.append(f"Completed: {report.completed_at}")
    lines.append("-" * 60)
    
    if hasattr(report, 'resources'):
        # Provisioning report
        lines.append(f"Total Resources: {len(report.resources)}")
        lines.append(f"  Created: {report.success_count}")
        lines.append(f"  Already Existed: {report.already_existed_count}")
        lines.append(f"  Failed: {report.failed_count}")
        lines.append(f"  Skipped: {report.skipped_count}")
        lines.append("-" * 60)
        lines.append("RESOURCE DETAILS:")
        
        for resource in report.resources:
            status_icon = _get_status_icon(resource.status)
            lines.append(f"  {status_icon} [{resource.status.value}] {resource.resource_name}")
            if resource.message:
                lines.append(f"      {resource.message}")
    
    elif hasattr(report, 'results'):
        # Verification report
        lines.append(f"Total Checks: {len(report.results)}")
        lines.append(f"  Passed: {report.passed_count}")
        lines.append(f"  Failed: {report.failed_count}")
        lines.append("-" * 60)
        lines.append("VERIFICATION DETAILS:")
        
        for result in report.results:
            status_icon = "[OK]" if result.status == VerificationStatusType.PASSED else "✗"
            lines.append(f"  {status_icon} [{result.status.value}] {result.resource_name}")
            if result.failure_reason:
                lines.append(f"      Reason: {result.failure_reason}")
    
    lines.append("-" * 60)
    overall = getattr(report, 'overall_success', getattr(report, 'all_passed', False))
    lines.append(f"OVERALL: {'SUCCESS' if overall else 'FAILED'}")
    lines.append("=" * 60)
    
    return "\n".join(lines)


def _get_status_icon(status: ResourceStatusType) -> str:
    """Get icon for resource status."""
    icons = {
        ResourceStatusType.CREATED: "[OK]",
        ResourceStatusType.ALREADY_EXISTS: "o",
        ResourceStatusType.FAILED: "✗",
        ResourceStatusType.SKIPPED: "->",
        ResourceStatusType.UPDATED: "[REFRESH]",
    }
    return icons.get(status, "?")


def cmd_provision(args):
    """Execute the provision command."""
    orchestrator = ProvisioningOrchestrator(
        environment=args.environment,
        region=args.region,
        dry_run=False,
        endpoint_url=args.endpoint_url,
    )
    
    if args.resource_type:
        # Provision specific resource type
        method_map = {
            "dynamodb": orchestrator.provision_dynamodb,
            "s3": orchestrator.provision_s3,
            "ssm": orchestrator.provision_ssm,
            "secrets": orchestrator.provision_secrets,
            "glue": orchestrator.provision_glue,
            "cloudwatch": orchestrator.provision_cloudwatch,
        }
        
        if args.resource_type not in method_map:
            print(f"Error: Unknown resource type '{args.resource_type}'")
            print(f"Valid types: {', '.join(method_map.keys())}")
            return 1
        
        results = method_map[args.resource_type]()
        # Create a minimal report for single resource type
        from .models import ProvisioningReport
        report = ProvisioningReport(
            environment=args.environment,
            region=args.region,
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            dry_run=False,
            resources=results,
        )
    else:
        report = orchestrator.provision_all()
    
    _output_report(report, "PROVISIONING", args.output)
    return 0 if report.overall_success else 1


def cmd_verify(args):
    """Execute the verify command."""
    verifier = VerificationService(
        environment=args.environment,
        region=args.region,
        endpoint_url=args.endpoint_url,
    )
    
    report = verifier.verify_all()
    _output_report(report, "VERIFICATION", args.output)
    return 0 if report.all_passed else 1


def cmd_dry_run(args):
    """Execute the dry-run command."""
    orchestrator = ProvisioningOrchestrator(
        environment=args.environment,
        region=args.region,
        dry_run=True,
        endpoint_url=args.endpoint_url,
    )
    
    report = orchestrator.provision_all()
    _output_report(report, "DRY RUN", args.output)
    return 0


def _output_report(report, report_type: str, output_format: str):
    """Output report in specified format."""
    if output_format == "json":
        print(json.dumps(asdict(report), indent=2, default=datetime_serializer))
    else:
        print(format_report_human(report, report_type))


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="infra-provisioning",
        description="Call Processing Infrastructure Provisioning CLI",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Common arguments for all subcommands
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-e", "--environment",
        required=True,
        choices=list(VALID_ENVIRONMENTS),
        help="Target environment",
    )
    common.add_argument(
        "-r", "--region",
        default="ap-southeast-1",
        help="AWS region (default: ap-southeast-1)",
    )
    common.add_argument(
        "-o", "--output",
        choices=["human", "json"],
        default="human",
        help="Output format (default: human)",
    )
    common.add_argument(
        "--endpoint-url",
        help="Custom AWS endpoint URL (for LocalStack)",
    )
    
    # Provision command
    provision_parser = subparsers.add_parser(
        "provision",
        parents=[common],
        help="Provision infrastructure resources",
    )
    provision_parser.add_argument(
        "-t", "--resource-type",
        choices=["dynamodb", "s3", "ssm", "secrets", "glue", "cloudwatch"],
        help="Provision specific resource type only",
    )
    provision_parser.set_defaults(func=cmd_provision)
    
    # Verify command
    verify_parser = subparsers.add_parser(
        "verify",
        parents=[common],
        help="Verify provisioned resources",
    )
    verify_parser.set_defaults(func=cmd_verify)
    
    # Dry-run command
    dry_run_parser = subparsers.add_parser(
        "dry-run",
        parents=[common],
        help="Show what would be provisioned without creating resources",
    )
    dry_run_parser.set_defaults(func=cmd_dry_run)
    
    return parser


def main(argv: Optional[list] = None) -> int:
    """Main entry point for CLI."""
    parser = create_parser()
    args = parser.parse_args(argv)
    
    if not args.command:
        parser.print_help()
        return 1
    
    setup_logging(args.verbose)
    
    try:
        return args.func(args)
    except Exception as e:
        logging.error(f"Error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
