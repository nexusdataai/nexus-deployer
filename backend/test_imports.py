"""Test script to verify TinyDB services can be imported"""
import sys
sys.path.insert(0, '.')

try:
    from app.services.tinydb_state_manager import TinyDBStateManager
    print("✓ TinyDBStateManager imported successfully")
    
    from app.services.tinydb_deployment_state_service import TinyDBDeploymentStateService
    print("✓ TinyDBDeploymentStateService imported successfully")
    
    from app.services.tinydb_capability_service import TinyDBCapabilityService
    print("✓ TinyDBCapabilityService imported successfully")
    
    from app.services.migration_service import MigrationService
    print("✓ MigrationService imported successfully")
    
    print("\n✓ All TinyDB services imported successfully!")
    
except Exception as e:
    print(f"✗ Import failed: {e}")
    sys.exit(1)
