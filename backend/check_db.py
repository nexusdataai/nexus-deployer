"""Check database content directly"""
from tinydb import TinyDB
from pathlib import Path

# Find the database
backend_dir = Path(__file__).parent
db_path = backend_dir / "data" / "state.db"

print(f"Checking database at: {db_path}")
print(f"Database exists: {db_path.exists()}")

if db_path.exists():
    db = TinyDB(str(db_path))
    
    # Check capabilities table
    capabilities_table = db.table("capabilities")
    capabilities = capabilities_table.all()
    
    print(f"\nCapabilities table: {len(capabilities)} entries")
    for cap in capabilities:
        print(f"  - {cap.get('name')} ({cap.get('id')})")
    
    # Check deployments table
    deployments_table = db.table("deployments")
    deployments = deployments_table.all()
    
    print(f"\nDeployments table: {len(deployments)} entries")
    
    db.close()
else:
    print("Database file does not exist!")
