"""
Verification script for Capability Update Detection feature
Demonstrates that all components are working correctly
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.stack_detection_service import StackDetectionService
from app.services.tinydb_deployment_state_service import TinyDBDeploymentStateService
from app.services.tinydb_state_manager import TinyDBStateManager
from app.models.stack_detection import DeploymentStrategy
import tempfile
import os

def test_detection_flow():
    """Test the complete detection flow"""
    print("=" * 80)
    print("CAPABILITY UPDATE DETECTION - VERIFICATION TEST")
    print("=" * 80)
    print()
    
    # Create temporary database
    temp_db = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    temp_db.close()
    
    try:
        # Initialize services
        print("1. Initializing services...")
        db_manager = TinyDBStateManager(db_path=temp_db.name)
        state_service = TinyDBDeploymentStateService(db_manager=db_manager)
        detection_service = StackDetectionService(state_service)
        print("   ✅ Services initialized")
        print()
        
        # Test 1: Detection with no existing deployment
        print("2. Testing detection with NO existing deployment...")
        result1 = detection_service.detect_existing_stacks(
            capability_name="test-capability",
            environment="dev"
        )
        print(f"   Has existing stacks: {result1.has_existing_stacks}")
        print(f"   Stacks found: {len(result1.stacks_found)}")
        print(f"   Is updatable: {result1.is_updatable}")
        assert not result1.has_existing_stacks, "Should have no existing stacks"
        print("   ✅ Detection works correctly for fresh deployment")
        print()
        
        # Test 2: Save deployment state
        print("3. Simulating successful deployment...")
        from datetime import datetime
        state_service.save_deployment_state(
            capability_name="test-capability",
            environment="dev",
            region="us-east-1",
            stacks=[
                {
                    "stack_name": "test-capability-dev-frontend-global",
                    "stack_type": "frontend-global",
                    "region": "us-east-1",
                    "deployed_at": datetime.utcnow().isoformat()
                },
                {
                    "stack_name": "test-capability-dev-backend-service",
                    "stack_type": "backend-service",
                    "region": "us-east-1",
                    "deployed_at": datetime.utcnow().isoformat()
                }
            ]
        )
        print("   ✅ Deployment state saved to TinyDB")
        print()
        
        # Test 3: Detection with existing deployment
        print("4. Testing detection WITH existing deployment...")
        result2 = detection_service.detect_existing_stacks(
            capability_name="test-capability",
            environment="dev"
        )
        print(f"   Has existing stacks: {result2.has_existing_stacks}")
        print(f"   Stacks found: {len(result2.stacks_found)}")
        print(f"   Is updatable: {result2.is_updatable}")
        print(f"   Has failed stacks: {result2.has_failed_stacks}")
        
        assert result2.has_existing_stacks, "Should have existing stacks"
        assert len(result2.stacks_found) == 2, "Should find 2 stacks"
        assert result2.is_updatable, "Should be updatable"
        assert not result2.has_failed_stacks, "Should have no failed stacks"
        
        print()
        print("   Stack details:")
        for stack in result2.stacks_found:
            print(f"     - {stack.stack_type}: {stack.stack_status}")
        print("   ✅ Detection works correctly for existing deployment")
        print()
        
        # Test 4: Strategy enum
        print("5. Testing deployment strategies...")
        print(f"   CLEAN_DEPLOY: {DeploymentStrategy.CLEAN_DEPLOY.value}")
        print(f"   UPDATE_EXISTING: {DeploymentStrategy.UPDATE_EXISTING.value}")
        print("   ✅ Strategy enum working correctly")
        print()
        
        # Test 5: Cleanup simulation
        print("6. Testing cleanup (delete deployment state)...")
        state_service.delete_deployment_state(
            capability_name="test-capability",
            environment="dev"
        )
        print("   ✅ Deployment state deleted from TinyDB")
        print()
        
        # Test 6: Verify cleanup
        print("7. Verifying cleanup...")
        result3 = detection_service.detect_existing_stacks(
            capability_name="test-capability",
            environment="dev"
        )
        print(f"   Has existing stacks: {result3.has_existing_stacks}")
        print(f"   Stacks found: {len(result3.stacks_found)}")
        assert not result3.has_existing_stacks, "Should have no stacks after cleanup"
        print("   ✅ Cleanup verified - no stacks found")
        print()
        
        # Summary
        print("=" * 80)
        print("✅ ALL VERIFICATION TESTS PASSED")
        print("=" * 80)
        print()
        print("Feature Status: FULLY OPERATIONAL")
        print()
        print("Components Verified:")
        print("  ✅ Stack Detection Service")
        print("  ✅ TinyDB State Management")
        print("  ✅ Detection with no existing stacks")
        print("  ✅ Detection with existing stacks")
        print("  ✅ Deployment state save")
        print("  ✅ Deployment state cleanup")
        print("  ✅ Strategy enum")
        print()
        print("The Capability Update Detection feature is ready for use!")
        print()
        
    finally:
        # Cleanup temp file
        try:
            # Close the database connection first
            if 'db_manager' in locals():
                db_manager.close()
            # Small delay to ensure file is released
            import time
            time.sleep(0.1)
            if os.path.exists(temp_db.name):
                os.unlink(temp_db.name)
        except Exception as e:
            print(f"Warning: Could not delete temp file: {e}")

if __name__ == "__main__":
    try:
        test_detection_flow()
        sys.exit(0)
    except Exception as e:
        print()
        print("=" * 80)
        print("❌ VERIFICATION FAILED")
        print("=" * 80)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
