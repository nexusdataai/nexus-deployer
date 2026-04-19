"""
Secure Credential Store
Encrypted credential storage using TinyDB with Fernet encryption
"""
import os
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from tinydb import Query
from cryptography.fernet import Fernet

from app.services.tinydb_state_manager import TinyDBStateManager, get_state_manager
from app.models.installation import StoredCredentials

logger = logging.getLogger(__name__)


class SecureCredentialStore:
    """
    Encrypted credential storage using TinyDB.
    
    Uses Fernet symmetric encryption to protect sensitive credential
    fields before storing in TinyDB. The encryption key is stored
    in a separate file in the data directory.
    """
    
    DEFAULT_RETENTION_HOURS = 24
    
    def __init__(self, db_manager: Optional[TinyDBStateManager] = None):
        """
        Initialize secure credential store.
        
        Args:
            db_manager: TinyDB state manager (uses global instance if None)
        """
        self.db_manager = db_manager or get_state_manager()
        self.table = self.db_manager.get_table("credentials_store")
        self.audit_table = self.db_manager.get_table("credential_audit_log")
        self._fernet = self._get_or_create_fernet()
        logger.info("SecureCredentialStore initialized")
    
    def _get_or_create_fernet(self) -> Fernet:
        """Get or create Fernet encryption instance with persistent key."""
        key_path = self.db_manager.db_path.parent / ".credential_key"
        
        if key_path.exists():
            with open(key_path, 'rb') as f:
                key = f.read()
            logger.debug("Loaded existing encryption key")
        else:
            key = Fernet.generate_key()
            # Ensure directory exists
            key_path.parent.mkdir(parents=True, exist_ok=True)
            with open(key_path, 'wb') as f:
                f.write(key)
            # Set restrictive permissions on key file
            try:
                os.chmod(key_path, 0o600)
            except Exception:
                pass  # Windows may not support chmod
            logger.info("Generated new encryption key")
        
        return Fernet(key)
    
    def _encrypt(self, plaintext: str) -> str:
        """Encrypt a string value."""
        return self._fernet.encrypt(plaintext.encode()).decode()
    
    def _decrypt(self, ciphertext: str) -> str:
        """Decrypt an encrypted string value."""
        return self._fernet.decrypt(ciphertext.encode()).decode()
    
    def _log_audit(
        self,
        installation_id: str,
        action: str,
        success: bool,
        details: Optional[str] = None
    ):
        """Log credential access for audit purposes without exposing values."""
        try:
            self.audit_table.insert({
                "timestamp": datetime.utcnow().isoformat(),
                "installation_id": installation_id,
                "action": action,
                "success": success,
                "details": details,
            })
        except Exception as e:
            logger.warning(f"Failed to write audit log: {e}")
    
    def store_credentials(
        self,
        installation_id: str,
        access_key_id: str,
        secret_access_key: str,
        session_token: Optional[str],
        region: str,
        account_id: str,
        expiration: Optional[datetime] = None,
        # ADFS authentication details for re-authentication
        adfs_url: Optional[str] = None,
        adfs_username: Optional[str] = None,
        adfs_password: Optional[str] = None,
        adfs_role_arn: Optional[str] = None,
        auth_method: Optional[str] = None
    ) -> bool:
        """
        Store encrypted credentials for an installation.
        
        Args:
            installation_id: Unique installation identifier
            access_key_id: AWS access key ID
            secret_access_key: AWS secret access key
            session_token: Optional AWS session token
            region: AWS region
            account_id: AWS account ID
            expiration: Optional credential expiration time
            adfs_url: ADFS endpoint URL for re-authentication
            adfs_username: ADFS username for re-authentication
            adfs_password: ADFS password for re-authentication
            adfs_role_arn: ADFS role ARN for re-authentication
            auth_method: Authentication method used (e.g., 'adfs_saml', 'access_key', 'profile')
            
        Returns:
            True if stored successfully
        """
        try:
            # Encrypt sensitive fields
            encrypted_access_key = self._encrypt(access_key_id)
            encrypted_secret_key = self._encrypt(secret_access_key)
            encrypted_session_token = self._encrypt(session_token) if session_token else None
            
            # Encrypt ADFS credentials if provided
            encrypted_adfs_url = self._encrypt(adfs_url) if adfs_url else None
            encrypted_adfs_username = self._encrypt(adfs_username) if adfs_username else None
            encrypted_adfs_password = self._encrypt(adfs_password) if adfs_password else None
            encrypted_adfs_role_arn = self._encrypt(adfs_role_arn) if adfs_role_arn else None
            
            # Create credential record
            creds = StoredCredentials(
                installation_id=installation_id,
                encrypted_access_key=encrypted_access_key,
                encrypted_secret_key=encrypted_secret_key,
                encrypted_session_token=encrypted_session_token,
                region=region,
                account_id=account_id,
                created_at=datetime.utcnow(),
                expires_at=expiration,
                last_accessed_at=None
            )
            
            # Convert to dict and add ADFS fields
            creds_dict = creds.to_dict()
            creds_dict['encrypted_adfs_url'] = encrypted_adfs_url
            creds_dict['encrypted_adfs_username'] = encrypted_adfs_username
            creds_dict['encrypted_adfs_password'] = encrypted_adfs_password
            creds_dict['encrypted_adfs_role_arn'] = encrypted_adfs_role_arn
            creds_dict['auth_method'] = auth_method
            
            # Remove existing credentials for this installation
            CredQuery = Query()
            self.table.remove(CredQuery.installation_id == installation_id)
            
            # Store new credentials
            self.table.insert(creds_dict)
            
            self._log_audit(installation_id, "store", True)
            logger.info(f"Stored credentials for installation {installation_id}")
            return True
            
        except Exception as e:
            self._log_audit(installation_id, "store", False, str(e))
            logger.error(f"Failed to store credentials: {e}")
            return False
    
    def get_credentials(self, installation_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve and decrypt credentials for an installation.
        
        Args:
            installation_id: Unique installation identifier
            
        Returns:
            Dict with decrypted credentials or None if not found
        """
        try:
            CredQuery = Query()
            result = self.table.get(CredQuery.installation_id == installation_id)
            
            if not result:
                self._log_audit(installation_id, "get", False, "not_found")
                return None
            
            # Decrypt sensitive fields
            decrypted = {
                "installation_id": result["installation_id"],
                "access_key_id": self._decrypt(result["encrypted_access_key"]),
                "secret_access_key": self._decrypt(result["encrypted_secret_key"]),
                "session_token": self._decrypt(result["encrypted_session_token"]) if result.get("encrypted_session_token") else None,
                "region": result["region"],
                "account_id": result["account_id"],
                "created_at": result["created_at"],
                "expires_at": result.get("expires_at"),
                "auth_method": result.get("auth_method"),
            }
            
            # Decrypt ADFS credentials if present
            if result.get("encrypted_adfs_url"):
                decrypted["adfs_url"] = self._decrypt(result["encrypted_adfs_url"])
            if result.get("encrypted_adfs_username"):
                decrypted["adfs_username"] = self._decrypt(result["encrypted_adfs_username"])
            if result.get("encrypted_adfs_password"):
                decrypted["adfs_password"] = self._decrypt(result["encrypted_adfs_password"])
            if result.get("encrypted_adfs_role_arn"):
                decrypted["adfs_role_arn"] = self._decrypt(result["encrypted_adfs_role_arn"])
            
            # Update last accessed timestamp
            self.table.update(
                {"last_accessed_at": datetime.utcnow().isoformat()},
                CredQuery.installation_id == installation_id
            )
            
            self._log_audit(installation_id, "get", True)
            logger.debug(f"Retrieved credentials for installation {installation_id}")
            return decrypted
            
        except Exception as e:
            self._log_audit(installation_id, "get", False, str(e))
            logger.error(f"Failed to get credentials: {e}")
            return None
    
    def delete_credentials(self, installation_id: str) -> bool:
        """
        Delete credentials for an installation.
        
        Args:
            installation_id: Unique installation identifier
            
        Returns:
            True if deleted successfully
        """
        try:
            CredQuery = Query()
            removed = self.table.remove(CredQuery.installation_id == installation_id)
            
            if removed:
                self._log_audit(installation_id, "delete", True)
                logger.info(f"Deleted credentials for installation {installation_id}")
            else:
                self._log_audit(installation_id, "delete", True, "not_found")
                logger.debug(f"No credentials found to delete for {installation_id}")
            
            return True
            
        except Exception as e:
            self._log_audit(installation_id, "delete", False, str(e))
            logger.error(f"Failed to delete credentials: {e}")
            return False
    
    def cleanup_expired(self, retention_hours: int = DEFAULT_RETENTION_HOURS) -> int:
        """
        Remove credentials older than retention period.
        
        Args:
            retention_hours: Hours to retain credentials after creation
            
        Returns:
            Number of credentials removed
        """
        try:
            cutoff = datetime.utcnow() - timedelta(hours=retention_hours)
            cutoff_iso = cutoff.isoformat()
            
            # Find expired credentials
            all_creds = self.table.all()
            expired_ids = []
            
            for cred in all_creds:
                created_at = cred.get("created_at", "")
                if created_at and created_at < cutoff_iso:
                    expired_ids.append(cred["installation_id"])
            
            # Remove expired credentials
            CredQuery = Query()
            removed_count = 0
            for install_id in expired_ids:
                self.table.remove(CredQuery.installation_id == install_id)
                self._log_audit(install_id, "cleanup_expired", True)
                removed_count += 1
            
            if removed_count > 0:
                logger.info(f"Cleaned up {removed_count} expired credentials")
            
            return removed_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup expired credentials: {e}")
            return 0
    
    def has_credentials(self, installation_id: str) -> bool:
        """
        Check if credentials exist for an installation.
        
        Args:
            installation_id: Unique installation identifier
            
        Returns:
            True if credentials exist
        """
        try:
            CredQuery = Query()
            return self.table.contains(CredQuery.installation_id == installation_id)
        except Exception:
            return False
    
    def can_reauthenticate(self, installation_id: str) -> bool:
        """
        Check if we have ADFS credentials to re-authenticate.
        
        Args:
            installation_id: Unique installation identifier
            
        Returns:
            True if ADFS credentials are stored and can be used for re-authentication
        """
        try:
            creds = self.get_credentials(installation_id)
            if not creds:
                return False
            
            # Check if we have ADFS credentials
            return (
                creds.get("auth_method") == "adfs_saml" and
                creds.get("adfs_url") and
                creds.get("adfs_username") and
                creds.get("adfs_password") and
                creds.get("adfs_role_arn")
            )
        except Exception:
            return False
    
    def reauthenticate_adfs(self, installation_id: str) -> Optional[Dict[str, Any]]:
        """
        Re-authenticate using stored ADFS credentials and update stored credentials.
        
        Args:
            installation_id: Unique installation identifier
            
        Returns:
            Dict with new credentials or None if re-authentication failed
        """
        try:
            # Get stored credentials with ADFS details
            stored_creds = self.get_credentials(installation_id)
            if not stored_creds:
                logger.warning(f"No stored credentials for installation {installation_id}")
                return None
            
            # Check if we have ADFS credentials
            if not self.can_reauthenticate(installation_id):
                logger.warning(f"No ADFS credentials available for re-authentication")
                return None
            
            # Import here to avoid circular imports
            from app.services.aws_auth_service import AWSAuthService
            
            adfs_url = stored_creds["adfs_url"]
            adfs_username = stored_creds["adfs_username"]
            adfs_password = stored_creds["adfs_password"]
            adfs_role_arn = stored_creds["adfs_role_arn"]
            region = stored_creds["region"]
            
            logger.info(f"Re-authenticating with ADFS for installation {installation_id}")
            
            # First, fetch roles to get a session
            roles_response = AWSAuthService.fetch_adfs_roles(
                adfs_url=adfs_url,
                username=adfs_username,
                password=adfs_password,
                region=region
            )
            
            if not roles_response.get("success"):
                logger.error(f"Failed to fetch ADFS roles: {roles_response.get('error')}")
                self._log_audit(installation_id, "reauthenticate", False, "fetch_roles_failed")
                return None
            
            session_id = roles_response.get("session_id")
            if not session_id:
                logger.error("No session ID returned from ADFS roles fetch")
                self._log_audit(installation_id, "reauthenticate", False, "no_session_id")
                return None
            
            # Select the role
            role_response = AWSAuthService.select_adfs_role(
                session_id=session_id,
                role_arn=adfs_role_arn,
                region=region
            )
            
            if not role_response.valid:
                logger.error(f"Failed to select ADFS role: {role_response.error}")
                self._log_audit(installation_id, "reauthenticate", False, "select_role_failed")
                return None
            
            # Get new credentials
            new_creds = role_response.credentials
            if not new_creds:
                logger.error("No credentials returned from role selection")
                self._log_audit(installation_id, "reauthenticate", False, "no_credentials")
                return None
            
            # Update stored credentials with new AWS credentials
            self.store_credentials(
                installation_id=installation_id,
                access_key_id=new_creds.get("access_key_id", ""),
                secret_access_key=new_creds.get("secret_access_key", ""),
                session_token=new_creds.get("session_token"),
                region=region,
                account_id=stored_creds["account_id"],
                # Keep ADFS credentials for future re-authentication
                adfs_url=adfs_url,
                adfs_username=adfs_username,
                adfs_password=adfs_password,
                adfs_role_arn=adfs_role_arn,
                auth_method="adfs_saml"
            )
            
            self._log_audit(installation_id, "reauthenticate", True)
            logger.info(f"Successfully re-authenticated for installation {installation_id}")
            
            return {
                "access_key_id": new_creds.get("access_key_id"),
                "secret_access_key": new_creds.get("secret_access_key"),
                "session_token": new_creds.get("session_token"),
                "region": region,
                "account_id": stored_creds["account_id"],
            }
            
        except Exception as e:
            self._log_audit(installation_id, "reauthenticate", False, str(e))
            logger.error(f"Failed to re-authenticate: {e}")
            return None
    
    def get_audit_log(
        self,
        installation_id: Optional[str] = None,
        limit: int = 100
    ) -> list:
        """
        Get audit log entries.
        
        Args:
            installation_id: Optional filter by installation
            limit: Maximum entries to return
            
        Returns:
            List of audit log entries
        """
        try:
            if installation_id:
                AuditQuery = Query()
                entries = self.audit_table.search(
                    AuditQuery.installation_id == installation_id
                )
            else:
                entries = self.audit_table.all()
            
            # Sort by timestamp descending and limit
            entries = sorted(entries, key=lambda x: x.get("timestamp", ""), reverse=True)
            return entries[:limit]
            
        except Exception as e:
            logger.error(f"Failed to get audit log: {e}")
            return []


# Global instance
_credential_store: Optional[SecureCredentialStore] = None


def get_credential_store() -> SecureCredentialStore:
    """Get global SecureCredentialStore instance."""
    global _credential_store
    if _credential_store is None:
        _credential_store = SecureCredentialStore()
    return _credential_store


def set_credential_store(store: Optional[SecureCredentialStore]):
    """Set global SecureCredentialStore instance (for testing)."""
    global _credential_store
    _credential_store = store
