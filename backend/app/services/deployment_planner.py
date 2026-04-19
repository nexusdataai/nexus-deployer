"""
Deployment Planner
Plans deployment order based on stack dependencies
"""
import logging
from typing import Dict, Any, List, Optional, Set
from collections import defaultdict

from app.models.dependency import (
    DependencyGraph,
    DependencyNode,
    DeploymentPlan,
    StackDeploymentStep,
    DeploymentAction,
    ValidationResult
)


logger = logging.getLogger(__name__)


class DeploymentPlanner:
    """Plans deployment order based on dependencies"""
    
    def topological_sort(self, graph: DependencyGraph) -> List[str]:
        """
        Perform topological sort to determine deployment order
        
        Uses Kahn's algorithm for deterministic ordering
        
        Args:
            graph: DependencyGraph to sort
            
        Returns:
            List of stack names in deployment order (dependencies first)
        """
        if not graph.nodes:
            return []
        
        # Calculate in-degrees (number of dependencies each node has)
        in_degree = {node_name: 0 for node_name in graph.nodes}
        
        for node_name, node in graph.nodes.items():
            for dep in node.depends_on:
                if dep in in_degree:
                    in_degree[node_name] += 1
        
        # Start with nodes that have no dependencies
        queue = [n for n in graph.nodes if in_degree[n] == 0]
        result = []
        
        while queue:
            # Sort for deterministic order
            queue.sort()
            node_name = queue.pop(0)
            result.append(node_name)
            
            # Reduce in-degree for nodes that depend on this one
            for other_name, other_node in graph.nodes.items():
                if node_name in other_node.depends_on:
                    in_degree[other_name] -= 1
                    if in_degree[other_name] == 0:
                        queue.append(other_name)
        
        # If result doesn't contain all nodes, there's a cycle
        if len(result) != len(graph.nodes):
            logger.warning("Topological sort incomplete - possible circular dependency")
            # Add remaining nodes at the end
            for node_name in graph.nodes:
                if node_name not in result:
                    result.append(node_name)
        
        return result

    def create_deployment_plan(self, 
                              graph: DependencyGraph,
                              existing_stacks: Dict[str, str],
                              validation_result: Optional[ValidationResult] = None) -> DeploymentPlan:
        """
        Create a deployment plan with proper ordering
        
        Args:
            graph: DependencyGraph with stack dependencies
            existing_stacks: Dict of stack_name -> status for existing stacks
            validation_result: Optional validation result with issues
            
        Returns:
            DeploymentPlan with ordered stack deployments
        """
        plan = DeploymentPlan()
        
        # Get deployment order
        deployment_order = self.topological_sort(graph)
        
        # Track which exports will be available at each step
        available_exports: Set[str] = set()
        
        for step_num, stack_name in enumerate(deployment_order, 1):
            node = graph.nodes.get(stack_name)
            if not node:
                continue
            
            # Determine action based on existing stack status
            stack_status = existing_stacks.get(stack_name)
            action, reason = self._determine_action(stack_status)
            
            # Calculate dependencies satisfied at this step
            deps_satisfied = []
            for dep in node.depends_on:
                dep_node = graph.nodes.get(dep)
                if dep_node:
                    for export in dep_node.exports:
                        if export.export_name in available_exports:
                            deps_satisfied.append(export.export_name)
            
            # Calculate exports this step will provide
            will_provide = [e.export_name for e in node.exports]
            
            step = StackDeploymentStep(
                step_number=step_num,
                stack_name=stack_name,
                stack_type=node.stack_type,
                action=action,
                reason=reason,
                dependencies_satisfied=deps_satisfied,
                will_provide_exports=will_provide
            )
            plan.add_step(step)
            
            # Add exports to available set
            available_exports.update(will_provide)
        
        # Set validation status
        plan.validation_passed = validation_result.success if validation_result else True
        
        # Add warnings from validation
        if validation_result:
            for issue in validation_result.issues:
                if issue.severity.value == 'warning':
                    plan.warnings.append(issue.description)
        
        # Estimate duration (rough estimate: 5 minutes per stack)
        plan.estimated_duration_minutes = plan.total_stacks * 5
        
        return plan
    
    def _determine_action(self, stack_status: Optional[str]) -> tuple:
        """
        Determine deployment action based on stack status
        
        Args:
            stack_status: Current stack status or None if doesn't exist
            
        Returns:
            Tuple of (DeploymentAction, reason string)
        """
        if stack_status is None:
            return DeploymentAction.CREATE, "Stack does not exist"
        
        # Stacks that need recreation
        failed_states = [
            'ROLLBACK_COMPLETE',
            'ROLLBACK_FAILED',
            'DELETE_FAILED',
            'CREATE_FAILED',
            'UPDATE_ROLLBACK_FAILED',
        ]
        
        if stack_status in failed_states:
            return DeploymentAction.CREATE, f"Stack in failed state ({stack_status}), will be recreated"
        
        # Stacks that can be updated
        updatable_states = [
            'CREATE_COMPLETE',
            'UPDATE_COMPLETE',
            'UPDATE_ROLLBACK_COMPLETE',
        ]
        
        if stack_status in updatable_states:
            return DeploymentAction.UPDATE, f"Stack exists ({stack_status}), will be updated"
        
        # In-progress states - skip
        in_progress_states = [
            'CREATE_IN_PROGRESS',
            'UPDATE_IN_PROGRESS',
            'DELETE_IN_PROGRESS',
            'ROLLBACK_IN_PROGRESS',
            'UPDATE_ROLLBACK_IN_PROGRESS',
        ]
        
        if stack_status in in_progress_states:
            return DeploymentAction.SKIP, f"Stack operation in progress ({stack_status})"
        
        # Default to update for unknown states
        return DeploymentAction.UPDATE, f"Stack status: {stack_status}"

    def identify_missing_stacks(self, 
                               required_exports: List[str],
                               graph: DependencyGraph,
                               existing_exports: Set[str]) -> List[str]:
        """
        Identify which stacks need to be deployed to satisfy dependencies
        
        Args:
            required_exports: List of export names that are needed
            graph: DependencyGraph with stack information
            existing_exports: Set of exports that already exist
            
        Returns:
            List of stack names that need to be deployed
        """
        missing_stacks = set()
        
        # Build export to stack mapping
        export_to_stack: Dict[str, str] = {}
        for node_name, node in graph.nodes.items():
            for export in node.exports:
                export_to_stack[export.export_name] = node_name
        
        # Find stacks that provide missing exports
        for export_name in required_exports:
            if export_name not in existing_exports:
                providing_stack = export_to_stack.get(export_name)
                if providing_stack:
                    missing_stacks.add(providing_stack)
        
        return list(missing_stacks)

    def generate_dry_run_report(self, plan: DeploymentPlan, 
                               validation_result: Optional[ValidationResult] = None) -> str:
        """
        Generate a human-readable dry-run report
        
        Args:
            plan: DeploymentPlan to report on
            validation_result: Optional validation result with issues
            
        Returns:
            Formatted report string
        """
        lines = []
        lines.append("=" * 70)
        lines.append("DRY-RUN DEPLOYMENT REPORT")
        lines.append("=" * 70)
        lines.append("")
        
        # Summary
        lines.append("SUMMARY")
        lines.append("-" * 40)
        lines.append(f"Total stacks: {plan.total_stacks}")
        lines.append(f"Estimated duration: {plan.estimated_duration_minutes} minutes")
        lines.append(f"Validation: {'PASSED' if plan.validation_passed else 'FAILED'}")
        lines.append("")
        
        # Validation issues
        if validation_result and validation_result.issues:
            lines.append("VALIDATION ISSUES")
            lines.append("-" * 40)
            for issue in validation_result.issues:
                severity_icon = "[X]" if issue.severity.value == 'error' else "[!]️"
                lines.append(f"{severity_icon} [{issue.severity.value.upper()}] {issue.description}")
                lines.append(f"   Stack: {issue.stack_name}")
                lines.append(f"   Action: {issue.suggested_action}")
            lines.append("")
        
        # Warnings
        if plan.warnings:
            lines.append("WARNINGS")
            lines.append("-" * 40)
            for warning in plan.warnings:
                lines.append(f"[!]️ {warning}")
            lines.append("")
        
        # Deployment steps
        lines.append("DEPLOYMENT PLAN")
        lines.append("-" * 40)
        
        for step in plan.steps:
            action_icon = {
                DeploymentAction.CREATE: "[NEW]",
                DeploymentAction.UPDATE: "[SYNC]",
                DeploymentAction.SKIP: "⏭️"
            }.get(step.action, "❓")
            
            lines.append(f"\nStep {step.step_number}: {step.stack_name}")
            lines.append(f"  {action_icon} Action: {step.action.value.upper()}")
            lines.append(f"  Type: {step.stack_type}")
            lines.append(f"  Reason: {step.reason}")
            
            if step.dependencies_satisfied:
                lines.append(f"  Dependencies satisfied: {len(step.dependencies_satisfied)}")
                for dep in step.dependencies_satisfied[:3]:  # Show first 3
                    lines.append(f"    - {dep}")
                if len(step.dependencies_satisfied) > 3:
                    lines.append(f"    ... and {len(step.dependencies_satisfied) - 3} more")
            
            if step.will_provide_exports:
                lines.append(f"  Will provide exports: {len(step.will_provide_exports)}")
                for exp in step.will_provide_exports[:3]:  # Show first 3
                    lines.append(f"    - {exp}")
                if len(step.will_provide_exports) > 3:
                    lines.append(f"    ... and {len(step.will_provide_exports) - 3} more")
        
        lines.append("")
        lines.append("=" * 70)
        
        if plan.validation_passed:
            lines.append("[OK] Dry-run complete. Deployment is likely to succeed.")
        else:
            lines.append("[X] Dry-run complete. Deployment will likely fail due to validation errors.")
        
        lines.append("=" * 70)
        
        return "\n".join(lines)
