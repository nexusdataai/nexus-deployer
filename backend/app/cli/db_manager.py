"""
Database Management CLI Utilities
Command-line tools for managing TinyDB database
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.tinydb_state_manager import get_state_manager
from app.services.tinydb_deployment_state_service import tinydb_deployment_state_service
from app.services.tinydb_capability_service import tinydb_capability_service


def backup_database(args):
    """Create a database backup"""
    try:
        db_manager = get_state_manager()
        backup_path = db_manager.backup(args.name)
        print(f"[OK] Database backup created: {backup_path}")
        return 0
    except Exception as e:
        print(f"✗ Backup failed: {e}")
        return 1


def restore_database(args):
    """Restore database from backup"""
    try:
        db_manager = get_state_manager()
        
        if not Path(args.backup_path).exists():
            print(f"✗ Backup file not found: {args.backup_path}")
            return 1
        
        if not args.force:
            response = input(f"This will replace the current database. Continue? (yes/no): ")
            if response.lower() != 'yes':
                print("Restore cancelled")
                return 0
        
        db_manager.restore(args.backup_path)
        print(f"[OK] Database restored from: {args.backup_path}")
        return 0
    except Exception as e:
        print(f"✗ Restore failed: {e}")
        return 1



def verify_database(args):
    """Verify database integrity"""
    try:
        db_manager = get_state_manager()
        
        print("Verifying database...")
        print(f"  Database path: {db_manager.db_path}")
        print(f"  Schema version: {db_manager.get_schema_version()}")
        
        # Check deployments
        deployments = tinydb_deployment_state_service.list_deployments()
        print(f"  Deployments: {len(deployments)}")
        
        # Check capabilities
        capabilities = tinydb_capability_service.get_all_capabilities()
        print(f"  Capabilities: {len(capabilities)}")
        
        print("[OK] Database verification complete")
        return 0
    except Exception as e:
        print(f"✗ Verification failed: {e}")
        return 1


def export_to_json(args):
    """Export TinyDB data to JSON files"""
    try:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Export deployments
        deployments = tinydb_deployment_state_service.list_deployments()
        deployments_file = output_dir / "deployments.json"
        with open(deployments_file, 'w') as f:
            json.dump(deployments, f, indent=2, default=str)
        print(f"[OK] Exported {len(deployments)} deployments to {deployments_file}")
        
        # Export capabilities
        capabilities = tinydb_capability_service.get_all_capabilities()
        capabilities_file = output_dir / "capabilities.json"
        with open(capabilities_file, 'w') as f:
            json.dump(capabilities, f, indent=2, default=str)
        print(f"[OK] Exported {len(capabilities)} capabilities to {capabilities_file}")
        
        print(f"[OK] Export complete: {output_dir}")
        return 0
    except Exception as e:
        print(f"✗ Export failed: {e}")
        return 1


def cleanup_backups(args):
    """Clean up old backups"""
    try:
        db_manager = get_state_manager()
        removed = db_manager.cleanup_old_backups(args.retention_days)
        print(f"[OK] Removed {removed} old backups (retention: {args.retention_days} days)")
        return 0
    except Exception as e:
        print(f"✗ Cleanup failed: {e}")
        return 1


def list_backups(args):
    """List available backups"""
    try:
        db_manager = get_state_manager()
        backup_dir = db_manager.backup_dir
        
        if not backup_dir.exists():
            print("No backups found")
            return 0
        
        backups = sorted(backup_dir.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        
        if not backups:
            print("No backups found")
            return 0
        
        print(f"Available backups ({len(backups)}):")
        for backup in backups:
            size_mb = backup.stat().st_size / (1024 * 1024)
            mtime = datetime.fromtimestamp(backup.stat().st_mtime)
            print(f"  {backup.name}")
            print(f"    Size: {size_mb:.2f} MB")
            print(f"    Modified: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")
        
        return 0
    except Exception as e:
        print(f"✗ Failed to list backups: {e}")
        return 1


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="TinyDB Database Management Utilities"
    )
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Backup command
    backup_parser = subparsers.add_parser('backup', help='Create database backup')
    backup_parser.add_argument('--name', help='Custom backup name')
    
    # Restore command
    restore_parser = subparsers.add_parser('restore', help='Restore from backup')
    restore_parser.add_argument('backup_path', help='Path to backup file')
    restore_parser.add_argument('--force', action='store_true', help='Skip confirmation')
    
    # Verify command
    verify_parser = subparsers.add_parser('verify', help='Verify database integrity')
    
    # Export command
    export_parser = subparsers.add_parser('export', help='Export data to JSON')
    export_parser.add_argument('--output-dir', default='./export', help='Output directory')
    
    # Cleanup command
    cleanup_parser = subparsers.add_parser('cleanup', help='Clean up old backups')
    cleanup_parser.add_argument('--retention-days', type=int, default=30, help='Retention period in days')
    
    # List backups command
    list_parser = subparsers.add_parser('list-backups', help='List available backups')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Execute command
    commands = {
        'backup': backup_database,
        'restore': restore_database,
        'verify': verify_database,
        'export': export_to_json,
        'cleanup': cleanup_backups,
        'list-backups': list_backups
    }
    
    return commands[args.command](args)


if __name__ == '__main__':
    sys.exit(main())
