"""
Test script for CloudFormation dependency validation
"""
import sys
import os

# Add the app directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.stack_dependency_analyzer import StackDependencyAnalyzer
from app.services.dependency_validator import DependencyValidator
from app.services.deployment_planner import DeploymentPlanner
from app.models.dependency import DependencyGraph, DependencyNode


def test_import_extraction():
    """Test that imports are correctly extracted from templates"""
    analyzer = StackDependencyAnalyzer()
    
    # Test template with Fn::ImportValue
    template = {
        'Resources': {
            'MyResource': {
                'Type': 'AWS::EC2::Instance',
                'Properties': {
                    'SubnetId': {'Fn::ImportValue': 'VPC-SubnetId'}
                }
            }
        }
    }
    
    imports = analyzer.extract_imports(template)
    assert len(imports) == 1, f"Expected 1 import, got {len(imports)}"
    assert imports[0].export_name == 'VPC-SubnetId', f"Expected 'VPC-SubnetId', got {imports[0].export_name}"
    print("[PASS] Import extraction test passed")


def test_export_extraction():
    """Test that exports are correctly extracted from templates"""
    analyzer = StackDependencyAnalyzer()
    
    template = {
        'Outputs': {
            'SubnetId': {
                'Value': {'Ref': 'MySubnet'},
                'Export': {
                    'Name': 'VPC-SubnetId'
                }
            }
        }
    }
    
    exports = analyzer.extract_exports(template)
    assert len(exports) == 1, f"Expected 1 export, got {len(exports)}"
    assert exports[0].export_name == 'VPC-SubnetId', f"Expected 'VPC-SubnetId', got {exports[0].export_name}"
    print("[PASS] Export extraction test passed")


def test_conditional_import():
    """Test that conditional imports are correctly identified"""
    analyzer = StackDependencyAnalyzer()
    
    template = {
        'Resources': {
            'MyResource': {
                'Type': 'AWS::EC2::Instance',
                'Properties': {
                    'SubnetId': {
                        'Fn::If': [
                            'UseCustomVPC',
                            {'Fn::ImportValue': 'Custom-VPC-SubnetId'},
                            {'Fn::ImportValue': 'Default-VPC-SubnetId'}
                        ]
                    }
                }
            }
        }
    }
    
    imports = analyzer.extract_imports(template)
    assert len(imports) == 2, f"Expected 2 imports, got {len(imports)}"
    
    # Check that conditions are tracked
    conditional_imports = [i for i in imports if i.is_conditional]
    assert len(conditional_imports) == 2, f"Expected 2 conditional imports, got {len(conditional_imports)}"
    print("[PASS] Conditional import test passed")


def test_topological_sort():
    """Test that topological sort produces correct ordering"""
    planner = DeploymentPlanner()
    
    # Create a simple dependency graph: A -> B -> C
    graph = DependencyGraph()
    
    node_a = DependencyNode(
        stack_name='stack-a',
        stack_type='foundation',
        template_path='',
        depends_on=[]
    )
    node_b = DependencyNode(
        stack_name='stack-b',
        stack_type='network',
        template_path='',
        depends_on=['stack-a']
    )
    node_c = DependencyNode(
        stack_name='stack-c',
        stack_type='service',
        template_path='',
        depends_on=['stack-b']
    )
    
    graph.add_node(node_a)
    graph.add_node(node_b)
    graph.add_node(node_c)
    
    order = planner.topological_sort(graph)
    
    # A should come before B, B should come before C
    assert order.index('stack-a') < order.index('stack-b'), "stack-a should come before stack-b"
    assert order.index('stack-b') < order.index('stack-c'), "stack-b should come before stack-c"
    print("[PASS] Topological sort test passed")


def test_circular_dependency_detection():
    """Test that circular dependencies are detected"""
    validator = DependencyValidator()
    
    # Create a circular dependency: A -> B -> C -> A
    graph = DependencyGraph()
    
    node_a = DependencyNode(
        stack_name='stack-a',
        stack_type='foundation',
        template_path='',
        depends_on=['stack-c']
    )
    node_b = DependencyNode(
        stack_name='stack-b',
        stack_type='network',
        template_path='',
        depends_on=['stack-a']
    )
    node_c = DependencyNode(
        stack_name='stack-c',
        stack_type='service',
        template_path='',
        depends_on=['stack-b']
    )
    
    graph.add_node(node_a)
    graph.add_node(node_b)
    graph.add_node(node_c)
    
    cycles = validator.detect_circular_dependencies(graph)
    
    assert len(cycles) > 0, "Expected at least one cycle to be detected"
    print("[PASS] Circular dependency detection test passed")


def test_deployment_plan_generation():
    """Test that deployment plans are correctly generated"""
    planner = DeploymentPlanner()
    
    # Create a simple graph
    graph = DependencyGraph()
    
    node_a = DependencyNode(
        stack_name='stack-a',
        stack_type='foundation',
        template_path='',
        depends_on=[]
    )
    node_b = DependencyNode(
        stack_name='stack-b',
        stack_type='service',
        template_path='',
        depends_on=['stack-a']
    )
    
    graph.add_node(node_a)
    graph.add_node(node_b)
    
    # Generate plan with no existing stacks
    plan = planner.create_deployment_plan(graph, {}, None)
    
    assert plan.total_stacks == 2, f"Expected 2 stacks, got {plan.total_stacks}"
    assert len(plan.steps) == 2, f"Expected 2 steps, got {len(plan.steps)}"
    print("[PASS] Deployment plan generation test passed")


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("Running CloudFormation Dependency Validation Tests")
    print("=" * 60 + "\n")
    
    try:
        test_import_extraction()
        test_export_extraction()
        test_conditional_import()
        test_topological_sort()
        test_circular_dependency_detection()
        test_deployment_plan_generation()
        
        print("\n" + "=" * 60)
        print("All tests passed!")
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
