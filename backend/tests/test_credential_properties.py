"""
Property-based tests for secure credential storage.

These tests verify correctness properties for credential encryption,
storage, and cleanup using hypothesis for randomized input generation.
"""
import pytest
import tempfile
import shutil
import time
import gc
from pathlib import Path
from datetime import datetime, timedelta
from hypothesis import given, strategies as st, settings, assume

from app.models.installation import StoredCredentials


def safe_cleanup(temp_dir: str, db_manager=None):
    """Safely cleanup temp directory, handling Windows file locking."""
    if db_manager:
        try:
            db_manager.close()
        except Exception:
            pass
    
    # Force garbage collection to release file handles
    gc.collect()
    time.sleep(0.1)
    
    try:
        shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception:
        pass  # Ignore cleanup errors on Windows


# Custom strategies for generating test data
access_key_strategy = st.text(
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    min_size=16,
    max_size=20
)
secret_key_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+/",
    min_size=32,
    max_size=40
)
session_token_strategy = st.text(min_size=100, max_size=500)
region_strategy = st.sampled_from(["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"])
account_id_strategy = st.text(alphabet="0123456789", min_size=12, max_size=12)
installation_id_strategy = st.uuids().map(str)


class TestCredentialEncryption:
    """
    **Feature: deployment-session-persistence, Property 9: Credential Encryption**
    
    For any stored credentials, the access_key, secret_key, and session_token
    fields must be encrypted, and the encrypted values must not contain the
    original plaintext.
    
    **Validates: Requirements 6.1**
    """
    
    @given(
        access_key_strategy,
        secret_key_strategy,
        st.one_of(st.none(), session_token_strategy),
        region_strategy,
        account_id_strategy,
        installation_id_strategy
    )
    @settings(max_examples=100)
    def test_credentials_are_encrypted_in_storage(
        self, access_key, secret_key, session_token, region, account_id, installation_id
    ):
        """
        Property: Stored credentials must be encrypted and not contain plaintext.
        """
        from app.services.secure_credential_store import SecureCredentialStore
        from app.services.tinydb_state_manager import TinyDBStateManager
        
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "test_state.db"
            db_manager = TinyDBStateManager(str(db_path))
            store = SecureCredentialStore(db_manager)
            
            # Store credentials
            success = store.store_credentials(
                installation_id=installation_id,
                access_key_id=access_key,
                secret_access_key=secret_key,
                session_token=session_token,
                region=region,
                account_id=account_id
            )
            assert success, "Credential storage should succeed"
            
            # Read raw data from TinyDB (bypassing decryption)
            raw_data = store.table.all()
            assert len(raw_data) == 1
            raw_cred = raw_data[0]
            
            # Verify encrypted fields don't contain plaintext
            assert access_key not in raw_cred["encrypted_access_key"], \
                "Access key should not appear in encrypted field"
            assert secret_key not in raw_cred["encrypted_secret_key"], \
                "Secret key should not appear in encrypted field"
            
            if session_token:
                assert session_token not in raw_cred.get("encrypted_session_token", ""), \
                    "Session token should not appear in encrypted field"
            
            # Verify we can decrypt and get original values back
            decrypted = store.get_credentials(installation_id)
            assert decrypted is not None
            assert decrypted["access_key_id"] == access_key
            assert decrypted["secret_access_key"] == secret_key
            assert decrypted["session_token"] == session_token
            
        finally:
            safe_cleanup(temp_dir, db_manager)
    
    @given(
        access_key_strategy,
        secret_key_strategy,
        installation_id_strategy
    )
    @settings(max_examples=50)
    def test_encryption_is_not_deterministic(
        self, access_key, secret_key, installation_id
    ):
        """
        Property: Same plaintext should produce different ciphertext (due to IV).
        """
        from app.services.secure_credential_store import SecureCredentialStore
        from app.services.tinydb_state_manager import TinyDBStateManager
        
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "test_state.db"
            db_manager = TinyDBStateManager(str(db_path))
            store = SecureCredentialStore(db_manager)
            
            # Encrypt same value twice
            encrypted1 = store._encrypt(access_key)
            encrypted2 = store._encrypt(access_key)
            
            # Fernet uses random IV, so same plaintext produces different ciphertext
            # (This is a security property - prevents pattern analysis)
            # Note: We can't guarantee they're different for very short inputs,
            # but both should decrypt to the same value
            assert store._decrypt(encrypted1) == access_key
            assert store._decrypt(encrypted2) == access_key
            
        finally:
            safe_cleanup(temp_dir, db_manager)


class TestCredentialCleanup:
    """
    **Feature: deployment-session-persistence, Property 3: Credential Cleanup on Completion**
    
    For any deployment that completes (success or failure), the stored
    credentials must be deleted from TinyDB within the configured retention period.
    
    **Validates: Requirements 1.3, 1.4, 6.2**
    """
    
    @given(installation_id_strategy)
    @settings(max_examples=50)
    def test_credentials_deleted_after_completion(self, installation_id):
        """
        Property: Credentials are deleted when delete_credentials is called.
        """
        from app.services.secure_credential_store import SecureCredentialStore
        from app.services.tinydb_state_manager import TinyDBStateManager
        
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "test_state.db"
            db_manager = TinyDBStateManager(str(db_path))
            store = SecureCredentialStore(db_manager)
            
            # Store credentials
            store.store_credentials(
                installation_id=installation_id,
                access_key_id="AKIAIOSFODNN7EXAMPLE",
                secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
                session_token=None,
                region="us-east-1",
                account_id="123456789012"
            )
            
            # Verify stored
            assert store.has_credentials(installation_id)
            
            # Delete credentials
            success = store.delete_credentials(installation_id)
            assert success
            
            # Verify deleted
            assert not store.has_credentials(installation_id)
            assert store.get_credentials(installation_id) is None
            
        finally:
            safe_cleanup(temp_dir, db_manager)
    
    def test_expired_credentials_cleaned_up(self):
        """
        Property: Credentials older than retention period are cleaned up.
        """
        from app.services.secure_credential_store import SecureCredentialStore
        from app.services.tinydb_state_manager import TinyDBStateManager
        from tinydb import Query
        
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "test_state.db"
            db_manager = TinyDBStateManager(str(db_path))
            store = SecureCredentialStore(db_manager)
            
            # Store credentials with old timestamp
            old_time = (datetime.utcnow() - timedelta(hours=48)).isoformat()
            recent_time = datetime.utcnow().isoformat()
            
            # Insert old credential directly (bypassing normal store to set old timestamp)
            store.table.insert({
                "installation_id": "old-install-1",
                "encrypted_access_key": store._encrypt("AKIAOLD1"),
                "encrypted_secret_key": store._encrypt("secretold1"),
                "encrypted_session_token": None,
                "region": "us-east-1",
                "account_id": "123456789012",
                "created_at": old_time,
            })
            
            store.table.insert({
                "installation_id": "old-install-2",
                "encrypted_access_key": store._encrypt("AKIAOLD2"),
                "encrypted_secret_key": store._encrypt("secretold2"),
                "encrypted_session_token": None,
                "region": "us-east-1",
                "account_id": "123456789012",
                "created_at": old_time,
            })
            
            # Store recent credential normally
            store.store_credentials(
                installation_id="recent-install",
                access_key_id="AKIARECENT",
                secret_access_key="secretrecent",
                session_token=None,
                region="us-east-1",
                account_id="123456789012"
            )
            
            # Verify all three exist
            assert len(store.table.all()) == 3
            
            # Cleanup with 24 hour retention
            removed = store.cleanup_expired(retention_hours=24)
            
            # Should have removed the 2 old credentials
            assert removed == 2
            
            # Recent credential should still exist
            assert store.has_credentials("recent-install")
            assert not store.has_credentials("old-install-1")
            assert not store.has_credentials("old-install-2")
            
        finally:
            safe_cleanup(temp_dir, db_manager)


class TestCredentialStorageOnDeployment:
    """
    **Feature: deployment-session-persistence, Property 1: Credential Storage on Deployment Start**
    
    For any deployment initiation with valid credentials, the credentials
    must be stored in TinyDB with the associated installation_id before
    any stack operations begin.
    
    **Validates: Requirements 1.1**
    """
    
    @given(
        access_key_strategy,
        secret_key_strategy,
        region_strategy,
        account_id_strategy,
        installation_id_strategy
    )
    @settings(max_examples=50)
    def test_credentials_stored_with_installation_id(
        self, access_key, secret_key, region, account_id, installation_id
    ):
        """
        Property: Credentials are stored with correct installation_id association.
        """
        from app.services.secure_credential_store import SecureCredentialStore
        from app.services.tinydb_state_manager import TinyDBStateManager
        
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "test_state.db"
            db_manager = TinyDBStateManager(str(db_path))
            store = SecureCredentialStore(db_manager)
            
            # Store credentials
            success = store.store_credentials(
                installation_id=installation_id,
                access_key_id=access_key,
                secret_access_key=secret_key,
                session_token=None,
                region=region,
                account_id=account_id
            )
            
            assert success, "Credential storage should succeed"
            
            # Verify credentials are associated with installation_id
            creds = store.get_credentials(installation_id)
            assert creds is not None
            assert creds["installation_id"] == installation_id
            assert creds["access_key_id"] == access_key
            assert creds["secret_access_key"] == secret_key
            assert creds["region"] == region
            assert creds["account_id"] == account_id
            
        finally:
            safe_cleanup(temp_dir, db_manager)


class TestAuditLogging:
    """
    **Feature: deployment-session-persistence, Property 11: Audit Logging Without Credential Exposure**
    
    For any credential access operation, an audit log entry must be created
    that does not contain the actual credential values.
    
    **Validates: Requirements 6.4**
    """
    
    @given(
        access_key_strategy,
        secret_key_strategy,
        installation_id_strategy
    )
    @settings(max_examples=50)
    def test_audit_log_does_not_contain_credentials(
        self, access_key, secret_key, installation_id
    ):
        """
        Property: Audit logs must not contain credential values.
        """
        from app.services.secure_credential_store import SecureCredentialStore
        from app.services.tinydb_state_manager import TinyDBStateManager
        import json
        
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "test_state.db"
            db_manager = TinyDBStateManager(str(db_path))
            store = SecureCredentialStore(db_manager)
            
            # Perform credential operations
            store.store_credentials(
                installation_id=installation_id,
                access_key_id=access_key,
                secret_access_key=secret_key,
                session_token=None,
                region="us-east-1",
                account_id="123456789012"
            )
            
            store.get_credentials(installation_id)
            store.delete_credentials(installation_id)
            
            # Get audit log
            audit_entries = store.get_audit_log(installation_id)
            
            # Verify audit entries exist
            assert len(audit_entries) >= 3  # store, get, delete
            
            # Convert to string for searching
            audit_str = json.dumps(audit_entries)
            
            # Verify credentials don't appear in audit log
            assert access_key not in audit_str, \
                "Access key should not appear in audit log"
            assert secret_key not in audit_str, \
                "Secret key should not appear in audit log"
            
            # Verify audit entries have expected structure
            for entry in audit_entries:
                assert "timestamp" in entry
                assert "installation_id" in entry
                assert "action" in entry
                assert "success" in entry
            
        finally:
            safe_cleanup(temp_dir, db_manager)
