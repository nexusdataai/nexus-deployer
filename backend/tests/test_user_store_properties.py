"""
Property-based tests for User Store Service.
Feature: user-authentication
Validates: Requirements 1.1, 1.2
"""
import pytest
import tempfile
import os
from hypothesis import given, strategies as st, settings, assume
from datetime import datetime

# Set up test database before imports
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.models.auth_models import UserCreate, UserRole
from app.services.tinydb_state_manager import TinyDBStateManager, set_state_manager
from app.services.user_store import UserStore, get_user_store, reset_user_store


@pytest.fixture(autouse=True)
def setup_test_db():
    """Set up a temporary test database for each test."""
    # Create temporary database file
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_state.db")
    
    # Create test database manager
    test_manager = TinyDBStateManager(db_path=db_path)
    set_state_manager(test_manager)
    reset_user_store()
    
    yield
    
    # Cleanup
    test_manager.close()
    set_state_manager(None)
    reset_user_store()
    
    # Remove temp files
    try:
        os.remove(db_path)
        os.rmdir(temp_dir)
    except:
        pass


# Strategies for generating test data
username_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N'), whitelist_characters='_-'),
    min_size=3,
    max_size=30
).filter(lambda x: len(x.strip()) >= 3)

email_strategy = st.emails()

password_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N', 'P')),
    min_size=12,
    max_size=50
).filter(lambda x: len(x) >= 12)


class TestUserStoreProperties:
    """Property-based tests for UserStore."""
    
    @settings(max_examples=100)
    @given(
        username=username_strategy,
        email=email_strategy,
        password=password_strategy
    )
    def test_property_1_valid_credentials_create_user(
        self, 
        username: str, 
        email: str, 
        password: str
    ):
        """
        Feature: user-authentication, Property 1: Valid credentials produce authenticated session
        
        For any valid username, email, and password combination,
        creating a user and verifying the password should succeed.
        
        Validates: Requirements 1.1
        """
        # Ensure unique username/email for this test
        unique_suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
        test_username = f"{username}_{unique_suffix}"[:50]
        test_email = f"{unique_suffix}_{email}"
        
        user_store = get_user_store()
        
        # Create user
        user_data = UserCreate(
            username=test_username,
            email=test_email,
            password=password,
            roles=[UserRole.VIEWER]
        )
        
        created_user = user_store.create_user(user_data)
        
        # Verify user was created
        assert created_user is not None
        assert created_user.username == test_username
        assert created_user.email == test_email
        
        # Verify password can be verified
        assert user_store.verify_password(password, created_user.password_hash) is True
        
        # Verify user can be retrieved
        retrieved_user = user_store.get_user_by_username(test_username)
        assert retrieved_user is not None
        assert retrieved_user.id == created_user.id
    
    @settings(max_examples=100)
    @given(
        username=username_strategy,
        email=email_strategy,
        password=password_strategy,
        wrong_password=password_strategy
    )
    def test_property_2_invalid_credentials_rejected(
        self,
        username: str,
        email: str,
        password: str,
        wrong_password: str
    ):
        """
        Feature: user-authentication, Property 2: Invalid credentials increment failure counter
        
        For any user, verifying with an incorrect password should fail
        and the failed login counter should be incremented.
        
        Validates: Requirements 1.2
        """
        # Ensure passwords are different
        assume(password != wrong_password)
        
        # Ensure unique username/email
        unique_suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
        test_username = f"{username}_{unique_suffix}"[:50]
        test_email = f"{unique_suffix}_{email}"
        
        user_store = get_user_store()
        
        # Create user
        user_data = UserCreate(
            username=test_username,
            email=test_email,
            password=password,
            roles=[UserRole.VIEWER]
        )
        
        created_user = user_store.create_user(user_data)
        
        # Verify wrong password fails
        assert user_store.verify_password(wrong_password, created_user.password_hash) is False
        
        # Increment failed login counter
        initial_count = created_user.failed_login_count
        new_count = user_store.increment_failed_login(test_username)
        
        # Verify counter was incremented by exactly 1
        assert new_count == initial_count + 1
        
        # Verify counter persisted
        updated_user = user_store.get_user_by_username(test_username)
        assert updated_user.failed_login_count == new_count
    
    @settings(max_examples=50)
    @given(
        username=username_strategy,
        email=email_strategy,
        password=password_strategy
    )
    def test_password_hash_is_not_plaintext(
        self,
        username: str,
        email: str,
        password: str
    ):
        """
        Verify that stored password hash is not the plaintext password.
        
        Validates: Security requirement for password storage
        """
        unique_suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
        test_username = f"{username}_{unique_suffix}"[:50]
        test_email = f"{unique_suffix}_{email}"
        
        user_store = get_user_store()
        
        user_data = UserCreate(
            username=test_username,
            email=test_email,
            password=password,
            roles=[UserRole.VIEWER]
        )
        
        created_user = user_store.create_user(user_data)
        
        # Password hash should not equal plaintext password
        assert created_user.password_hash != password
        
        # Password hash should be longer than typical passwords
        assert len(created_user.password_hash) > len(password)
    
    @settings(max_examples=50)
    @given(
        username=username_strategy,
        email=email_strategy,
        password=password_strategy
    )
    def test_failed_login_reset_on_success(
        self,
        username: str,
        email: str,
        password: str
    ):
        """
        Feature: user-authentication, Property 7: Successful authentication resets failure counter
        
        For any user with failed login attempts, resetting the counter
        should set it to zero.
        
        Validates: Requirements 1.7
        """
        unique_suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
        test_username = f"{username}_{unique_suffix}"[:50]
        test_email = f"{unique_suffix}_{email}"
        
        user_store = get_user_store()
        
        user_data = UserCreate(
            username=test_username,
            email=test_email,
            password=password,
            roles=[UserRole.VIEWER]
        )
        
        user_store.create_user(user_data)
        
        # Simulate some failed attempts
        user_store.increment_failed_login(test_username)
        user_store.increment_failed_login(test_username)
        user_store.increment_failed_login(test_username)
        
        # Verify counter is > 0
        user = user_store.get_user_by_username(test_username)
        assert user.failed_login_count > 0
        
        # Reset counter (simulating successful login)
        user_store.reset_failed_login(test_username)
        
        # Verify counter is 0
        user = user_store.get_user_by_username(test_username)
        assert user.failed_login_count == 0


class TestUserStoreCRUD:
    """Unit tests for UserStore CRUD operations."""
    
    def test_create_user_success(self):
        """Test successful user creation."""
        user_store = get_user_store()
        
        user_data = UserCreate(
            username="testuser",
            email="test@example.com",
            password="SecurePassword123!",
            roles=[UserRole.OPERATOR]
        )
        
        user = user_store.create_user(user_data)
        
        assert user.id is not None
        assert user.username == "testuser"
        assert user.email == "test@example.com"
        assert UserRole.OPERATOR in user.roles
        assert user.require_password_change is True
    
    def test_create_duplicate_username_fails(self):
        """Test that duplicate username raises error."""
        from app.services.user_store import UserAlreadyExistsError
        
        user_store = get_user_store()
        
        user_data = UserCreate(
            username="duplicateuser",
            email="first@example.com",
            password="SecurePassword123!",
            roles=[UserRole.VIEWER]
        )
        
        user_store.create_user(user_data)
        
        # Try to create another user with same username
        user_data2 = UserCreate(
            username="duplicateuser",
            email="second@example.com",
            password="AnotherPassword123!",
            roles=[UserRole.VIEWER]
        )
        
        with pytest.raises(UserAlreadyExistsError):
            user_store.create_user(user_data2)
    
    def test_get_user_by_id(self):
        """Test retrieving user by ID."""
        user_store = get_user_store()
        
        user_data = UserCreate(
            username="idtestuser",
            email="idtest@example.com",
            password="SecurePassword123!",
            roles=[UserRole.VIEWER]
        )
        
        created = user_store.create_user(user_data)
        retrieved = user_store.get_user_by_id(created.id)
        
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.username == created.username
    
    def test_get_nonexistent_user_returns_none(self):
        """Test that getting nonexistent user returns None."""
        user_store = get_user_store()
        
        result = user_store.get_user_by_id("nonexistent-id")
        assert result is None
        
        result = user_store.get_user_by_username("nonexistent-user")
        assert result is None
    
    def test_update_user(self):
        """Test updating user fields."""
        user_store = get_user_store()
        
        user_data = UserCreate(
            username="updatetestuser",
            email="update@example.com",
            password="SecurePassword123!",
            roles=[UserRole.VIEWER]
        )
        
        created = user_store.create_user(user_data)
        
        # Update user
        updated = user_store.update_user(created.id, {
            "email": "newemail@example.com",
            "roles": [UserRole.OPERATOR]
        })
        
        assert updated is not None
        assert updated.email == "newemail@example.com"
        assert UserRole.OPERATOR in updated.roles
    
    def test_delete_user(self):
        """Test deleting a user."""
        user_store = get_user_store()
        
        user_data = UserCreate(
            username="deletetestuser",
            email="delete@example.com",
            password="SecurePassword123!",
            roles=[UserRole.VIEWER]
        )
        
        created = user_store.create_user(user_data)
        
        # Delete user
        result = user_store.delete_user(created.id)
        assert result is True
        
        # Verify user is gone
        retrieved = user_store.get_user_by_id(created.id)
        assert retrieved is None
