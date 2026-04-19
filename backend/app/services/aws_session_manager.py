"""
AWS Session Manager
Manages AWS credentials and sessions for deployments with optional persistence
"""
import os
import tempfile
import logging
from typing import Optional, Dict
from datetime import datetime, timedelta
import uuid

logger = logging.getLogger(__name__)


class AWSSessionManager:
    """
    Manages AWS credentials and sessions with optional persistence.
    
    Enhanced to support:
    - Credential persistence in TinyDB for long-running deployments
    - Automatic credential refresh on expiration
    - Installation-based credential tracking
    """
    
    def __init__(self, credential_store=None):
        """
        Initialize session manager.
        
        Args:
            credential_store: Optional SecureCredentialStore for persistence
        """
        self.sessions: Dict[str, Dict] = {}
        self.session_ttl = timedelta(hours=1)  # Sessions expire after 1 hour
        self._credential_store = credential_store
        self._installation_sessions: Dict[str, str] = {}  # installation_id -> session_id
    
    @property
    def credential_store(self):
        """Lazy load credential store to avoid circular imports."""
        if self._credential_store is None:
            try:
                from app.services.secure_credential_store import get_credential_store
                self._credential_store = get_credential_store()
            except Exception as e:
                logger.warning(f"Could not load credential store: {e}")
        return self._credential_store
    
    def create_session(self, 
                      access_key_id: str,
                      secret_access_key: str,
                      session_token: Optional[str] = None,
                      region: Optional[str] = None,
                      account_id: Optional[str] = None) -> str:
        """
        Create a new AWS session and return session ID
        """
        session_id = str(uuid.uuid4())
        
        self.sessions[session_id] = {
            "access_key_id": access_key_id,
            "secret_access_key": secret_access_key,
            "session_token": session_token,
            "region": region,
            "account_id": account_id,
            "created_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + self.session_ttl,
            "installation_id": None,
        }
        
        return session_id
    
    def create_session_with_persistence(
        self,
        installation_id: str,
        access_key_id: str,
        secret_access_key: str,
        session_token: Optional[str] = None,
        region: Optional[str] = None,
        account_id: Optional[str] = None,
        # ADFS credentials for re-authentication
        adfs_url: Optional[str] = None,
        adfs_username: Optional[str] = None,
        adfs_password: Optional[str] = None,
        adfs_role_arn: Optional[str] = None,
        auth_method: Optional[str] = None
    ) -> str:
        """
        Create session and persist credentials for long-running deployments.
        
        Args:
            installation_id: Unique installation identifier
            access_key_id: AWS access key ID
            secret_access_key: AWS secret access key
            session_token: Optional AWS session token
            region: AWS region
            account_id: AWS account ID
            adfs_url: ADFS endpoint URL for re-authentication
            adfs_username: ADFS username for re-authentication
            adfs_password: ADFS password for re-authentication
            adfs_role_arn: ADFS role ARN for re-authentication
            auth_method: Authentication method used
            
        Returns:
            Session ID
        """
        # Create in-memory session
        session_id = self.create_session(
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            session_token=session_token,
            region=region,
            account_id=account_id
        )
        
        # Link session to installation
        self.sessions[session_id]["installation_id"] = installation_id
        self._installation_sessions[installation_id] = session_id
        
        # Persist credentials including ADFS details for re-authentication
        if self.credential_store:
            try:
                self.credential_store.store_credentials(
                    installation_id=installation_id,
                    access_key_id=access_key_id,
                    secret_access_key=secret_access_key,
                    session_token=session_token,
                    region=region or "us-east-1",
                    account_id=account_id or "",
                    adfs_url=adfs_url,
                    adfs_username=adfs_username,
                    adfs_password=adfs_password,
                    adfs_role_arn=adfs_role_arn,
                    auth_method=auth_method
                )
                logger.info(f"Persisted credentials for installation {installation_id}")
            except Exception as e:
                logger.warning(f"Failed to persist credentials: {e}")
        
        return session_id
        
        return session_id
    
    def refresh_session(self, session_id: str) -> bool:
        """
        Attempt to refresh expired session using stored credentials.
        If ADFS credentials are stored, re-authenticate with ADFS.
        
        Args:
            session_id: Session ID to refresh
            
        Returns:
            True if refresh successful
        """
        if session_id not in self.sessions:
            logger.warning(f"Session {session_id} not found for refresh")
            return False
        
        session = self.sessions[session_id]
        installation_id = session.get("installation_id")
        
        if not installation_id:
            logger.warning("No installation_id associated with session")
            return False
        
        if not self.credential_store:
            logger.warning("No credential store available for refresh")
            return False
        
        try:
            # First, try ADFS re-authentication if available
            if self.credential_store.can_reauthenticate(installation_id):
                logger.info(f"Attempting ADFS re-authentication for session {session_id}")
                new_creds = self.credential_store.reauthenticate_adfs(installation_id)
                
                if new_creds:
                    # Update session with new credentials
                    self.sessions[session_id].update({
                        "access_key_id": new_creds["access_key_id"],
                        "secret_access_key": new_creds["secret_access_key"],
                        "session_token": new_creds.get("session_token"),
                        "region": new_creds.get("region"),
                        "account_id": new_creds.get("account_id"),
                        "expires_at": datetime.utcnow() + self.session_ttl,
                    })
                    logger.info(f"Refreshed session {session_id} via ADFS re-authentication")
                    return True
                else:
                    logger.warning("ADFS re-authentication failed, falling back to stored credentials")
            
            # Fallback: Get stored credentials (may be expired but try anyway)
            stored_creds = self.credential_store.get_credentials(installation_id)
            
            if not stored_creds:
                logger.warning(f"No stored credentials for installation {installation_id}")
                return False
            
            # Update session with stored credentials
            self.sessions[session_id].update({
                "access_key_id": stored_creds["access_key_id"],
                "secret_access_key": stored_creds["secret_access_key"],
                "session_token": stored_creds.get("session_token"),
                "region": stored_creds.get("region"),
                "account_id": stored_creds.get("account_id"),
                "expires_at": datetime.utcnow() + self.session_ttl,
            })
            
            logger.info(f"Refreshed session {session_id} from stored credentials")
            return True
            
        except Exception as e:
            logger.error(f"Failed to refresh session: {e}")
            return False
    
    def get_session_for_installation(self, installation_id: str) -> Optional[str]:
        """
        Get session ID for an installation.
        
        Args:
            installation_id: Installation identifier
            
        Returns:
            Session ID or None
        """
        return self._installation_sessions.get(installation_id)
    
    def cleanup_installation_credentials(self, installation_id: str):
        """
        Remove credentials after deployment completes.
        
        Args:
            installation_id: Installation identifier
        """
        # Remove from installation mapping
        session_id = self._installation_sessions.pop(installation_id, None)
        
        # Delete in-memory session
        if session_id and session_id in self.sessions:
            del self.sessions[session_id]
        
        # Delete persisted credentials
        if self.credential_store:
            try:
                self.credential_store.delete_credentials(installation_id)
                logger.info(f"Cleaned up credentials for installation {installation_id}")
            except Exception as e:
                logger.warning(f"Failed to cleanup credentials: {e}")
    
    def startup_cleanup(self, retention_hours: int = 24):
        """
        Clean up orphaned credentials on application startup.
        
        Args:
            retention_hours: Hours to retain credentials
        """
        if self.credential_store:
            try:
                removed = self.credential_store.cleanup_expired(retention_hours)
                if removed > 0:
                    logger.info(f"Startup cleanup removed {removed} expired credentials")
            except Exception as e:
                logger.warning(f"Startup cleanup failed: {e}")
    
    def get_session(self, session_id: str) -> Optional[Dict]:
        """Get session by ID, attempting refresh if expired"""
        if session_id not in self.sessions:
            return None
        
        session = self.sessions[session_id]
        
        # Check if expired
        if datetime.utcnow() > session["expires_at"]:
            # Try to refresh from stored credentials
            if self.refresh_session(session_id):
                return self.sessions[session_id]
            
            # Refresh failed, remove session
            del self.sessions[session_id]
            return None
        
        return session
    
    def delete_session(self, session_id: str):
        """Delete a session"""
        if session_id in self.sessions:
            del self.sessions[session_id]
    
    def cleanup_expired_sessions(self):
        """Remove expired sessions"""
        now = datetime.utcnow()
        expired = [sid for sid, session in self.sessions.items() 
                  if now > session["expires_at"]]
        
        for sid in expired:
            del self.sessions[sid]
    
    def get_credentials_dict(self, session_id: str) -> Optional[Dict[str, str]]:
        """Get credentials as dictionary for boto3"""
        session = self.get_session(session_id)
        if not session:
            return None
        
        creds = {
            "aws_access_key_id": session["access_key_id"],
            "aws_secret_access_key": session["secret_access_key"],
        }
        
        if session.get("session_token"):
            creds["aws_session_token"] = session["session_token"]
        
        if session.get("region"):
            creds["region_name"] = session["region"]
        
        return creds
    
    def get_env_vars(self, session_id: str) -> Optional[Dict[str, str]]:
        """Get credentials as environment variables"""
        session = self.get_session(session_id)
        if not session:
            return None
        
        env_vars = {
            "AWS_ACCESS_KEY_ID": session["access_key_id"],
            "AWS_SECRET_ACCESS_KEY": session["secret_access_key"],
            "AWS_DEFAULT_REGION": session.get("region", "us-east-1"),
        }
        
        if session.get("session_token"):
            env_vars["AWS_SESSION_TOKEN"] = session["session_token"]
        
        return env_vars
    
    def create_credentials_file(self, session_id: str) -> Optional[str]:
        """
        Create a temporary AWS credentials file
        Returns the path to the credentials file
        """
        session = self.get_session(session_id)
        if not session:
            return None
        
        # Create temporary credentials file
        temp_dir = tempfile.mkdtemp()
        creds_file = os.path.join(temp_dir, "credentials")
        
        with open(creds_file, 'w') as f:
            f.write("[default]\n")
            f.write(f"aws_access_key_id = {session['access_key_id']}\n")
            f.write(f"aws_secret_access_key = {session['secret_access_key']}\n")
            
            if session.get("session_token"):
                f.write(f"aws_session_token = {session['session_token']}\n")
        
        return creds_file
    
    def extend_session(self, session_id: str):
        """Extend session expiration time"""
        if session_id in self.sessions:
            self.sessions[session_id]["expires_at"] = datetime.utcnow() + self.session_ttl


# Global session manager instance
aws_session_manager = AWSSessionManager()
