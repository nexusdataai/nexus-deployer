"""
Test script for TinyDB-based Stack Detection Service
"""
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.stack_detection_service import StackDetectionService
from app.services.tinydb_deployment_state_service import tinydb_deployment_state_service


def test_detection_no_existing_deployment():
    """Test detection when no deployment exists"""
    print("Test 1: Detection with no existing deployment")
    
    detection_service = StackDetectionService()
    
    result = detection_service.detect_existing_stacks(
        capability_name="nonexistent-capability",
        environment="dev"
    )
    
    assert result.has_existing_stacks == False, "Should not have existing stacks"
    assert len(result.stacks_found) == 0, "Should have no stacks"
    print("  ✓ Correctly detected no existing deployment")
    print()


def test_detection_with_existing_deployment():
    """Test detection when deployment exists"""
    print("Test 2: Detection with existing deployment")
    
    # Create a test deployment in TinyDB
    test_capability = "test-capability-detection"
    test_environment = "dev"
    
    # Save test deployment state
    tinydb_deployment_state_service.save_deployment_state(
        capability_name=test_capability,
        environment=test_environment,
        region="us-east-1",
        stacks=[
            {
                "stack_name": f"{test_capability}-{test_environment}-backend-foundation",
                "stack_type": "backend-foundation",
                "status": "DEPLOYED"
            },
            {
                "stack_name": f"{test_capability}-{test_environment}-backend-storage",
                "stack_type": "backend-storage",
                "status": "DEPLOYED"
            }
        ],
        deployment_metadata={
            "test": True
        }
    )
    
    # Detect the deployment
    detection_service = StackDetectionService()
    result = detection_service.detect_existing_stacks(
        capability_name=test_capability,
        environment=test_environment
    )
    
    assert result.has_existing_stacks == True, "Should have existing stacks"
    assert len(result.stacks_found) == 2, f"Should have 2 stacks, got {len(result.stacks_found)}"
    assert result.region == "us-east-1", "Should have correct region"
    
    print(f"  ✓ Detected {len(result.stacks_found)} stacks")
    for stack in result.stacks_found:
        print(f"    - {stack.stack_name} ({stack.stack_type})")
    
    # Cleanup test data
    tinydb_deployment_state_service.delete_deployment_state(
        test_capability, test_environment
    )
    print("  ✓ Cleaned up test data")
    print()


def test_detection_result_structure():
    """Test that detection result has correct structure"""
    print("Test 3: Detection result structure")
    
    detection_service = StackDetectionService()
    
    result = detection_service.detect_existing_stacks(
        capability_name="test-capability",
        environment="prod"
    )
    
    # Check all required fields exist
    assert hasattr(result, 'capability_name'), "Should have capability_name"
    assert hasattr(result, 'environment'), "Should have environment"
    assert hasattr(result, 'region'), "Should have region"
    assert hasattr(result, 'stacks_found'), "Should have stacks_found"
    assert hasattr(result, 'has_existing_stacks'), "Should have has_existing_stacks"
    assert hasattr(result, 'detection_timestamp'), "Should have detection_timestamp"
    
    print("  ✓ Detection result has all required fields")
    print()


if __name__ == '__main__':
    print("=" * 60)
    print("TinyDB-based Stack Detection Service Tests")
    print("=" * 60)
    print()
    
    try:
        test_detection_no_existing_deployment()
        test_detection_with_existing_deployment()
        test_detection_result_structure()
        
        print("=" * 60)
        print("✓ ALL TESTS PASSED!")
        print("=" * 60)
    except Exception as e:
        print(f"\n❌ TEST FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
