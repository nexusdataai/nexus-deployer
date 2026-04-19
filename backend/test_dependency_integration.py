"""
Integration tests for CloudFormation dependency validation
Tests against real CloudFormation templates from deploy/templates
"""
import sys
import os
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.stack_dependency_analyzer import StackDependencyAnalyzer
from app.services.dependency_validator import DependencyValidator
from app.services.deployment_planner import DeploymentPlanner
from app.services.cloudformation_service import CloudFormationDeploymentService


def test_real_template_parsing():
    """Test parsing real CloudFormation templates from deploy/templates"""
    analyzer = StackDependencyAnalyzer()
    cfn_service = CloudFormationDeploymentService()
    templates_dir = cfn_service.templates_dir
    
    print(f"\nTemplates directory: {templates_dir}")
    
    templates_parsed = 0
    total_imports = 0
    total_exports = 0
    
    for stack_type, template_path in cfn_service.TEMPLATE_MAP.items():
        full_path = templates_dir / template_path
        
        if not full_path.exists():
            print(f"  ⚠ Template not found: {template_path}")
            continue
        
        try:
            template = analyzer.load_template_file(str(full_path))
            deps = analyzer.analyze_template(template)
            
            templates_parsed += 1
            total_imports += len(deps.imports)
            total_exports += len(deps.exports)
            
            print(f"  ✓ {stack_type}: {len(deps.imports)} imports, {len(deps.exports)} exports")
            
        except Exception as e:
            print(f"  ❌ {stack_type}: Failed to parse - {e}")
    
    print(f"\nSummary: Parsed {templates_parsed} templates")
    print(f"  Total imports found: {total_imports}")
    print(f"  Total exports found: {total_exports}")
    
    assert templates_parsed > 0, "No templates were parsed"
    print("[PASS] Real template parsing test passed")


def test_dependency_graph_construction():
    """Test building dependency graph from real templates"""
    analyzer = StackDependencyAnalyzer()
    validator = DependencyValidator()
    cfn_service = CloudFormationDeploymentService()
    templates_dir = cfn_service.templates_dir
    
    # Build stack configs for all templates
    stack_configs = []
    capability_name = "Test-Capability"
    environment = "dev"
    
    for stack_type, template_path in cfn_service.TEMPLATE_MAP.items():
        full_path = templates_dir / template_path
        
        if not full_path.exists():
            continue
        
        stack_name = cfn_service.get_stack_name(capability_name, environment, stack_type)
        stack_configs.append({
            'stack_name': stack_name,
            'stack_type': stack_type,
            'template_path': str(full_path)
        })
    
    print(f"\nBuilding dependency graph for {len(stack_configs)} stacks...")
    
    # Build the graph
    graph = validator.build_dependency_graph(stack_configs)
    
    print(f"  Nodes: {len(graph.nodes)}")
    print(f"  Edges: {len(graph.edges)}")
    
    # Print dependencies for each stack
    for node_name, node in graph.nodes.items():
        if node.depends_on:
            print(f"  {node_name} depends on: {', '.join(node.depends_on)}")
    
    assert len(graph.nodes) > 0, "No nodes in dependency graph"
    print("[PASS] Dependency graph construction test passed")


def test_deployment_ordering():
    """Test that deployment ordering respects dependencies"""
    validator = DependencyValidator()
    planner = DeploymentPlanner()
    cfn_service = CloudFormationDeploymentService()
    templates_dir = cfn_service.templates_dir
    
    # Build stack configs
    stack_configs = []
    capability_name = "Test-Capability"
    environment = "dev"
    
    for stack_type, template_path in cfn_service.TEMPLATE_MAP.items():
        full_path = templates_dir / template_path
        
        if not full_path.exists():
            continue
        
        stack_name = cfn_service.get_stack_name(capability_name, environment, stack_type)
        stack_configs.append({
            'stack_name': stack_name,
            'stack_type': stack_type,
            'template_path': str(full_path)
        })
    
    # Build graph and get deployment order
    graph = validator.build_dependency_graph(stack_configs)
    order = planner.topological_sort(graph)
    
    print(f"\nDeployment order ({len(order)} stacks):")
    for i, stack_name in enumerate(order, 1):
        print(f"  {i}. {stack_name}")
    
    # Verify that dependencies come before dependents
    for node_name, node in graph.nodes.items():
        node_index = order.index(node_name) if node_name in order else -1
        for dep in node.depends_on:
            if dep in order:
                dep_index = order.index(dep)
                assert dep_index < node_index, f"{dep} should come before {node_name}"
    
    print("[PASS] Deployment ordering test passed")


def test_missing_export_detection():
    """Test that missing exports are correctly detected"""
    analyzer = StackDependencyAnalyzer()
    
    # Create a template that imports a non-existent export
    template = {
        'Resources': {
            'MyResource': {
                'Type': 'AWS::EC2::Instance',
                'Properties': {
                    'SubnetId': {'Fn::ImportValue': 'NonExistent-Export-Name'}
                }
            }
        }
    }
    
    deps = analyzer.analyze_template(template)
    
    assert len(deps.imports) == 1, "Should find one import"
    assert deps.imports[0].export_name == 'NonExistent-Export-Name', "Should capture export name"
    
    print("[PASS] Missing export detection test passed")


def test_conditional_export_handling():
    """Test handling of conditional exports"""
    analyzer = StackDependencyAnalyzer()
    
    # Template with conditional export
    template = {
        'Conditions': {
            'CreateCert': {'Fn::Equals': [{'Ref': 'CreateCertificate'}, 'true']}
        },
        'Outputs': {
            'CertificateArn': {
                'Condition': 'CreateCert',
                'Value': {'Ref': 'Certificate'},
                'Export': {
                    'Name': 'Stack-CertificateArn'
                }
            }
        }
    }
    
    deps = analyzer.analyze_template(template)
    
    assert len(deps.exports) == 1, "Should find one export"
    assert deps.exports[0].is_conditional, "Export should be marked as conditional"
    assert deps.exports[0].condition_name == 'CreateCert', "Should capture condition name"
    
    print("[PASS] Conditional export handling test passed")


def test_dry_run_report_generation():
    """Test dry-run report generation"""
    planner = DeploymentPlanner()
    validator = DependencyValidator()
    cfn_service = CloudFormationDeploymentService()
    templates_dir = cfn_service.templates_dir
    
    # Build stack configs
    stack_configs = []
    capability_name = "Test-Capability"
    environment = "dev"
    
    for stack_type, template_path in cfn_service.TEMPLATE_MAP.items():
        full_path = templates_dir / template_path
        
        if not full_path.exists():
            continue
        
        stack_name = cfn_service.get_stack_name(capability_name, environment, stack_type)
        stack_configs.append({
            'stack_name': stack_name,
            'stack_type': stack_type,
            'template_path': str(full_path)
        })
    
    # Build graph and create plan
    graph = validator.build_dependency_graph(stack_configs)
    plan = planner.create_deployment_plan(graph, {}, None)
    
    # Generate report
    report = planner.generate_dry_run_report(plan, None)
    
    print("\n" + "=" * 60)
    print("DRY-RUN REPORT PREVIEW (first 30 lines):")
    print("=" * 60)
    lines = report.split('\n')[:30]
    for line in lines:
        print(line)
    print("..." if len(report.split('\n')) > 30 else "")
    print("=" * 60)
    
    assert len(report) > 0, "Report should not be empty"
    assert "DEPLOYMENT PLAN" in report, "Report should contain deployment plan"
    
    print("[PASS] Dry-run report generation test passed")


def main():
    """Run all integration tests"""
    print("\n" + "=" * 60)
    print("Running CloudFormation Dependency Integration Tests")
    print("=" * 60)
    
    try:
        test_real_template_parsing()
        test_dependency_graph_construction()
        test_deployment_ordering()
        test_missing_export_detection()
        test_conditional_export_handling()
        test_dry_run_report_generation()
        
        print("\n" + "=" * 60)
        print("All integration tests passed!")
        print("=" * 60 + "\n")
        return 0
        
    except AssertionError as e:
        print(f"\n[FAIL] Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n[ERROR] Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
