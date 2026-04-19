"""Script to manually load capabilities into TinyDB"""
import sys
from pathlib import Path

sys.path.insert(0, '.')

from app.services.tinydb_capability_service import tinydb_capability_service
from app.services.tinydb_state_manager import get_state_manager

# Check database path
db_manager = get_state_manager()
print(f"Database path: {db_manager.db_path}")

# Load capabilities
backend_dir = Path(__file__).parent
capabilities_json = backend_dir / "capabilities" / "capabilities.json"

print(f"Loading capabilities from: {capabilities_json}")

if capabilities_json.exists():
    success = tinydb_capability_service.load_capabilities_from_json(str(capabilities_json))
    if success:
        print("✓ Successfully loaded capabilities")
        
        # Verify
        capabilities = tinydb_capability_service.get_all_capabilities()
        print(f"✓ Loaded {len(capabilities)} capabilities:")
        for cap in capabilities:
            print(f"  - {cap.get('name')} ({cap.get('id')})")
        
        # Close database to flush to disk
        print("\nFlushing database to disk...")
        db_manager.close()
        print("✓ Database closed and flushed")
    else:
        print("✗ Failed to load capabilities")
else:
    print(f"✗ Capabilities file not found: {capabilities_json}")
