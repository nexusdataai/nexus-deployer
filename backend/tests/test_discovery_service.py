"""
Unit tests for DiscoveryService stack name parsing.

Feature: capability-discovery

Tests cover:
- Valid stack names are parsed correctly
- All stack types are recognized
- All environments are recognized
- Invalid stack names return None
- Edge cases (hyphens in capability name)

Validates: Requirements 4.3, 4.4, 4.6
"""
import pytest
from app.services.discovery.discovery_service import (
    DiscoveryService,
    KNOWN_STACK_TYPES,
    VALID_ENVIRONMENTS,
)


class TestParseStackNameValidStackTypes:
    """
    **Feature: capability-discovery, Requirement 4.4: Stack Type Recognition**
    
    Tests that all valid stack types are recognized by parse_stack_name.
    
    **Validates: Requirement 4.4**
    """
    
    @pytest.fixture
    def discovery_service(self):
        """Create a DiscoveryService instance for testing."""
        return DiscoveryService(region="us-east-1")
    
    def test_backend_foundation_stack_type(self, discovery_service):
        """Test backend-foundation stack type is recognized."""
        result = discovery_service.parse_stack_name("MyCapability-prod-backend-foundation")
        assert result is not None
        assert result == ("MyCapability", "prod", "backend-foundation")
    
    def test_backend_iam_roles_stack_type(self, discovery_service):
        """Test backend-iam-roles stack type is recognized."""
        result = discovery_service.parse_stack_name("MyCapability-prod-backend-iam-roles")
        assert result is not None
        assert result == ("MyCapability", "prod", "backend-iam-roles")
    
    def test_backend_regional_cert_stack_type(self, discovery_service):
        """Test backend-regional-cert stack type is recognized."""
        result = discovery_service.parse_stack_name("MyCapability-prod-backend-regional-cert")
        assert result is not None
        assert result == ("MyCapability", "prod", "backend-regional-cert")
    
    def test_backend_storage_stack_type(self, discovery_service):
        """Test backend-storage stack type is recognized."""
        result = discovery_service.parse_stack_name("MyCapability-prod-backend-storage")
        assert result is not None
        assert result == ("MyCapability", "prod", "backend-storage")
    
    def test_backend_network_stack_type(self, discovery_service):
        """Test backend-network stack type is recognized."""
        result = discovery_service.parse_stack_name("MyCapability-prod-backend-network")
        assert result is not None
        assert result == ("MyCapability", "prod", "backend-network")
    
    def test_backend_service_stack_type(self, discovery_service):
        """Test backend-service stack type is recognized."""
        result = discovery_service.parse_stack_name("MyCapability-prod-backend-service")
        assert result is not None
        assert result == ("MyCapability", "prod", "backend-service")
    
    def test_backend_domain_stack_type(self, discovery_service):
        """Test backend-domain stack type is recognized."""
        result = discovery_service.parse_stack_name("MyCapability-prod-backend-domain")
        assert result is not None
        assert result == ("MyCapability", "prod", "backend-domain")
    
    def test_frontend_global_stack_type(self, discovery_service):
        """Test frontend-global stack type is recognized."""
        result = discovery_service.parse_stack_name("MyCapability-prod-frontend-global")
        assert result is not None
        assert result == ("MyCapability", "prod", "frontend-global")
    
    def test_frontend_cognito_stack_type(self, discovery_service):
        """Test frontend-cognito stack type is recognized."""
        result = discovery_service.parse_stack_name("MyCapability-prod-frontend-cognito")
        assert result is not None
        assert result == ("MyCapability", "prod", "frontend-cognito")
    
    def test_frontend_regional_stack_type(self, discovery_service):
        """Test frontend-regional stack type is recognized."""
        result = discovery_service.parse_stack_name("MyCapability-prod-frontend-regional")
        assert result is not None
        assert result == ("MyCapability", "prod", "frontend-regional")
    
    def test_all_known_stack_types_recognized(self, discovery_service):
        """Test that all KNOWN_STACK_TYPES are recognized."""
        for stack_type in KNOWN_STACK_TYPES:
            stack_name = f"TestCapability-dev-{stack_type}"
            result = discovery_service.parse_stack_name(stack_name)
            assert result is not None, f"Stack type '{stack_type}' should be recognized"
            assert result[2] == stack_type, f"Stack type should be '{stack_type}'"


class TestParseStackNameValidEnvironments:
    """
    **Feature: capability-discovery, Requirement 4.3: Environment Extraction**
    
    Tests that all valid environments are recognized by parse_stack_name.
    
    **Validates: Requirement 4.3**
    """
    
    @pytest.fixture
    def discovery_service(self):
        """Create a DiscoveryService instance for testing."""
        return DiscoveryService(region="us-east-1")
    
    def test_dev_environment(self, discovery_service):
        """Test dev environment is recognized."""
        result = discovery_service.parse_stack_name("MyCapability-dev-backend-service")
        assert result is not None
        assert result == ("MyCapability", "dev", "backend-service")
    
    def test_test_environment(self, discovery_service):
        """Test test environment is recognized."""
        result = discovery_service.parse_stack_name("MyCapability-test-backend-service")
        assert result is not None
        assert result == ("MyCapability", "test", "backend-service")
    
    def test_stage_environment(self, discovery_service):
        """Test stage environment is recognized."""
        result = discovery_service.parse_stack_name("MyCapability-stage-backend-service")
        assert result is not None
        assert result == ("MyCapability", "stage", "backend-service")
    
    def test_prod_environment(self, discovery_service):
        """Test prod environment is recognized."""
        result = discovery_service.parse_stack_name("MyCapability-prod-backend-service")
        assert result is not None
        assert result == ("MyCapability", "prod", "backend-service")
    
    def test_all_valid_environments_recognized(self, discovery_service):
        """Test that all VALID_ENVIRONMENTS are recognized."""
        for env in VALID_ENVIRONMENTS:
            stack_name = f"TestCapability-{env}-backend-service"
            result = discovery_service.parse_stack_name(stack_name)
            assert result is not None, f"Environment '{env}' should be recognized"
            assert result[1] == env, f"Environment should be '{env}'"


class TestParseStackNameInvalidInputs:
    """
    **Feature: capability-discovery, Requirement 4.6: Skip Non-Matching Stacks**
    
    Tests that invalid stack names return None without error.
    
    **Validates: Requirement 4.6**
    """
    
    @pytest.fixture
    def discovery_service(self):
        """Create a DiscoveryService instance for testing."""
        return DiscoveryService(region="us-east-1")
    
    def test_empty_string_returns_none(self, discovery_service):
        """Test empty string returns None."""
        result = discovery_service.parse_stack_name("")
        assert result is None
    
    def test_random_stack_name_returns_none(self, discovery_service):
        """Test random stack name returns None."""
        result = discovery_service.parse_stack_name("some-random-stack-name")
        assert result is None
    
    def test_missing_environment_returns_none(self, discovery_service):
        """Test stack name without environment returns None."""
        result = discovery_service.parse_stack_name("MyCapability-backend-service")
        assert result is None
    
    def test_missing_stack_type_returns_none(self, discovery_service):
        """Test stack name without stack type returns None."""
        result = discovery_service.parse_stack_name("MyCapability-prod")
        assert result is None
    
    def test_invalid_environment_returns_none(self, discovery_service):
        """Test stack name with invalid environment returns None."""
        result = discovery_service.parse_stack_name("MyCapability-production-backend-service")
        assert result is None
    
    def test_invalid_stack_type_returns_none(self, discovery_service):
        """Test stack name with invalid stack type returns None."""
        result = discovery_service.parse_stack_name("MyCapability-prod-backend-invalid")
        assert result is None
    
    def test_partial_stack_type_returns_none(self, discovery_service):
        """Test stack name with partial stack type returns None."""
        result = discovery_service.parse_stack_name("MyCapability-prod-backend")
        assert result is None
    
    def test_only_capability_name_returns_none(self, discovery_service):
        """Test only capability name returns None."""
        result = discovery_service.parse_stack_name("MyCapability")
        assert result is None
    
    def test_aws_cdk_stack_returns_none(self, discovery_service):
        """Test AWS CDK bootstrap stack returns None."""
        result = discovery_service.parse_stack_name("CDKToolkit")
        assert result is None
    
    def test_cloudformation_stack_returns_none(self, discovery_service):
        """Test generic CloudFormation stack returns None."""
        result = discovery_service.parse_stack_name("my-application-stack")
        assert result is None
    
    def test_similar_but_invalid_stack_type_returns_none(self, discovery_service):
        """Test similar but invalid stack type returns None."""
        result = discovery_service.parse_stack_name("MyCapability-prod-backend-services")
        assert result is None
    
    def test_uppercase_environment_returns_none(self, discovery_service):
        """Test uppercase environment returns None (case sensitive)."""
        result = discovery_service.parse_stack_name("MyCapability-PROD-backend-service")
        assert result is None
    
    def test_uppercase_stack_type_returns_none(self, discovery_service):
        """Test uppercase stack type returns None (case sensitive)."""
        result = discovery_service.parse_stack_name("MyCapability-prod-BACKEND-SERVICE")
        assert result is None


class TestParseStackNameEdgeCases:
    """
    **Feature: capability-discovery, Requirement 4.3: Capability Name Extraction**
    
    Tests edge cases including hyphens in capability names.
    
    **Validates: Requirement 4.3**
    """
    
    @pytest.fixture
    def discovery_service(self):
        """Create a DiscoveryService instance for testing."""
        return DiscoveryService(region="us-east-1")
    
    def test_capability_name_with_single_hyphen(self, discovery_service):
        """Test capability name with single hyphen is parsed correctly."""
        result = discovery_service.parse_stack_name("Call-Processing-prod-backend-service")
        assert result is not None
        assert result == ("Call-Processing", "prod", "backend-service")
    
    def test_capability_name_with_multiple_hyphens(self, discovery_service):
        """Test capability name with multiple hyphens is parsed correctly."""
        result = discovery_service.parse_stack_name("My-Complex-Capability-Name-prod-backend-service")
        assert result is not None
        assert result == ("My-Complex-Capability-Name", "prod", "backend-service")
    
    def test_capability_name_with_numbers(self, discovery_service):
        """Test capability name with numbers is parsed correctly."""
        result = discovery_service.parse_stack_name("Capability123-prod-backend-service")
        assert result is not None
        assert result == ("Capability123", "prod", "backend-service")
    
    def test_capability_name_with_numbers_and_hyphens(self, discovery_service):
        """Test capability name with numbers and hyphens is parsed correctly."""
        result = discovery_service.parse_stack_name("My-Capability-v2-prod-backend-service")
        assert result is not None
        assert result == ("My-Capability-v2", "prod", "backend-service")
    
    def test_single_character_capability_name(self, discovery_service):
        """Test single character capability name is parsed correctly."""
        result = discovery_service.parse_stack_name("A-prod-backend-service")
        assert result is not None
        assert result == ("A", "prod", "backend-service")
    
    def test_long_capability_name(self, discovery_service):
        """Test long capability name is parsed correctly."""
        long_name = "Very-Long-Capability-Name-With-Many-Parts"
        result = discovery_service.parse_stack_name(f"{long_name}-prod-backend-service")
        assert result is not None
        assert result == (long_name, "prod", "backend-service")
    
    def test_capability_name_ending_with_number(self, discovery_service):
        """Test capability name ending with number is parsed correctly."""
        result = discovery_service.parse_stack_name("MyCapability2-prod-backend-service")
        assert result is not None
        assert result == ("MyCapability2", "prod", "backend-service")
    
    def test_capability_name_starting_with_number(self, discovery_service):
        """Test capability name starting with number is parsed correctly."""
        result = discovery_service.parse_stack_name("123Capability-prod-backend-service")
        assert result is not None
        assert result == ("123Capability", "prod", "backend-service")
    
    def test_capability_name_all_lowercase(self, discovery_service):
        """Test all lowercase capability name is parsed correctly."""
        result = discovery_service.parse_stack_name("mycapability-prod-backend-service")
        assert result is not None
        assert result == ("mycapability", "prod", "backend-service")
    
    def test_capability_name_all_uppercase(self, discovery_service):
        """Test all uppercase capability name is parsed correctly."""
        result = discovery_service.parse_stack_name("MYCAPABILITY-prod-backend-service")
        assert result is not None
        assert result == ("MYCAPABILITY", "prod", "backend-service")
    
    def test_capability_name_mixed_case(self, discovery_service):
        """Test mixed case capability name is parsed correctly."""
        result = discovery_service.parse_stack_name("MyCapability-prod-backend-service")
        assert result is not None
        assert result == ("MyCapability", "prod", "backend-service")


class TestParseStackNameRealWorldExamples:
    """
    **Feature: capability-discovery, Requirements 4.3, 4.4**
    
    Tests with real-world stack name examples.
    
    **Validates: Requirements 4.3, 4.4**
    """
    
    @pytest.fixture
    def discovery_service(self):
        """Create a DiscoveryService instance for testing."""
        return DiscoveryService(region="us-east-1")
    
    def test_call_processing_prod_backend_service(self, discovery_service):
        """Test Call-Processing-prod-backend-service example from spec."""
        result = discovery_service.parse_stack_name("Call-Processing-prod-backend-service")
        assert result is not None
        assert result == ("Call-Processing", "prod", "backend-service")
    
    def test_billing_dev_frontend_global(self, discovery_service):
        """Test billing capability frontend stack."""
        result = discovery_service.parse_stack_name("Billing-dev-frontend-global")
        assert result is not None
        assert result == ("Billing", "dev", "frontend-global")
    
    def test_user_management_stage_backend_foundation(self, discovery_service):
        """Test user management capability backend foundation stack."""
        result = discovery_service.parse_stack_name("User-Management-stage-backend-foundation")
        assert result is not None
        assert result == ("User-Management", "stage", "backend-foundation")
    
    def test_analytics_test_backend_storage(self, discovery_service):
        """Test analytics capability backend storage stack."""
        result = discovery_service.parse_stack_name("Analytics-test-backend-storage")
        assert result is not None
        assert result == ("Analytics", "test", "backend-storage")
    
    def test_notification_service_prod_frontend_cognito(self, discovery_service):
        """Test notification service frontend cognito stack."""
        result = discovery_service.parse_stack_name("Notification-Service-prod-frontend-cognito")
        assert result is not None
        assert result == ("Notification-Service", "prod", "frontend-cognito")
    
    def test_api_gateway_dev_backend_network(self, discovery_service):
        """Test API gateway backend network stack."""
        result = discovery_service.parse_stack_name("API-Gateway-dev-backend-network")
        assert result is not None
        assert result == ("API-Gateway", "dev", "backend-network")
    
    def test_data_pipeline_stage_backend_iam_roles(self, discovery_service):
        """Test data pipeline backend IAM roles stack."""
        result = discovery_service.parse_stack_name("Data-Pipeline-stage-backend-iam-roles")
        assert result is not None
        assert result == ("Data-Pipeline", "stage", "backend-iam-roles")
    
    def test_reporting_prod_frontend_regional(self, discovery_service):
        """Test reporting frontend regional stack."""
        result = discovery_service.parse_stack_name("Reporting-prod-frontend-regional")
        assert result is not None
        assert result == ("Reporting", "prod", "frontend-regional")
    
    def test_auth_service_test_backend_domain(self, discovery_service):
        """Test auth service backend domain stack."""
        result = discovery_service.parse_stack_name("Auth-Service-test-backend-domain")
        assert result is not None
        assert result == ("Auth-Service", "test", "backend-domain")
    
    def test_monitoring_dev_backend_regional_cert(self, discovery_service):
        """Test monitoring backend regional cert stack."""
        result = discovery_service.parse_stack_name("Monitoring-dev-backend-regional-cert")
        assert result is not None
        assert result == ("Monitoring", "dev", "backend-regional-cert")


class TestParseStackNameStackTypeOrdering:
    """
    **Feature: capability-discovery, Requirement 4.4**
    
    Tests that stack types with similar prefixes are correctly distinguished.
    This ensures the longest-match-first algorithm works correctly.
    
    **Validates: Requirement 4.4**
    """
    
    @pytest.fixture
    def discovery_service(self):
        """Create a DiscoveryService instance for testing."""
        return DiscoveryService(region="us-east-1")
    
    def test_backend_iam_roles_not_confused_with_backend(self, discovery_service):
        """Test backend-iam-roles is not confused with a shorter match."""
        result = discovery_service.parse_stack_name("MyCapability-prod-backend-iam-roles")
        assert result is not None
        assert result[2] == "backend-iam-roles"
    
    def test_backend_regional_cert_not_confused_with_backend(self, discovery_service):
        """Test backend-regional-cert is not confused with a shorter match."""
        result = discovery_service.parse_stack_name("MyCapability-prod-backend-regional-cert")
        assert result is not None
        assert result[2] == "backend-regional-cert"
    
    def test_frontend_regional_not_confused_with_frontend(self, discovery_service):
        """Test frontend-regional is not confused with a shorter match."""
        result = discovery_service.parse_stack_name("MyCapability-prod-frontend-regional")
        assert result is not None
        assert result[2] == "frontend-regional"
    
    def test_frontend_cognito_not_confused_with_frontend(self, discovery_service):
        """Test frontend-cognito is not confused with a shorter match."""
        result = discovery_service.parse_stack_name("MyCapability-prod-frontend-cognito")
        assert result is not None
        assert result[2] == "frontend-cognito"
    
    def test_frontend_global_not_confused_with_frontend(self, discovery_service):
        """Test frontend-global is not confused with a shorter match."""
        result = discovery_service.parse_stack_name("MyCapability-prod-frontend-global")
        assert result is not None
        assert result[2] == "frontend-global"


class TestParseStackNameCapabilityNameExtraction:
    """
    **Feature: capability-discovery, Requirement 4.3**
    
    Tests that capability names are correctly extracted from stack names.
    
    **Validates: Requirement 4.3**
    """
    
    @pytest.fixture
    def discovery_service(self):
        """Create a DiscoveryService instance for testing."""
        return DiscoveryService(region="us-east-1")
    
    def test_empty_capability_name_returns_none(self, discovery_service):
        """Test that empty capability name returns None."""
        # This would be "-prod-backend-service" which has no capability name
        result = discovery_service.parse_stack_name("-prod-backend-service")
        assert result is None
    
    def test_capability_name_preserved_exactly(self, discovery_service):
        """Test that capability name is preserved exactly as in stack name."""
        result = discovery_service.parse_stack_name("ExactName-prod-backend-service")
        assert result is not None
        assert result[0] == "ExactName"
    
    def test_capability_name_with_special_characters_preserved(self, discovery_service):
        """Test capability name with underscores is preserved."""
        # Note: CloudFormation stack names can contain underscores
        result = discovery_service.parse_stack_name("My_Capability-prod-backend-service")
        assert result is not None
        assert result[0] == "My_Capability"


# =============================================================================
# Status Determination Tests
# =============================================================================


class TestDetermineCapabilityStatusFailed:
    """
    **Feature: capability-discovery, Requirement 5.3: Failed Status Detection**
    
    Tests that FAILED status is correctly detected and takes priority over other statuses.
    When any stack is in a FAILED or ROLLBACK state, mark the capability as "Failed".
    
    **Validates: Requirement 5.3**
    """
    
    @pytest.fixture
    def discovery_service(self):
        """Create a DiscoveryService instance for testing."""
        return DiscoveryService(region="us-east-1")
    
    def _create_stack(self, stack_type: str, status: str) -> "DiscoveredStack":
        """Helper to create a DiscoveredStack for testing."""
        from app.services.discovery.models import DiscoveredStack
        return DiscoveredStack(
            stack_name=f"TestCapability-prod-{stack_type}",
            stack_type=stack_type,
            stack_status=status,
            region="us-east-1",
        )
    
    def test_create_failed_status_returns_failed(self, discovery_service):
        """Test CREATE_FAILED status returns FAILED."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("backend-foundation", "CREATE_FAILED"),
        ]
        stack_types_found = {"backend-foundation"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.FAILED
        assert missing == []
    
    def test_update_failed_status_returns_failed(self, discovery_service):
        """Test UPDATE_FAILED status returns FAILED."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("backend-service", "UPDATE_FAILED"),
        ]
        stack_types_found = {"backend-service"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.FAILED
        assert missing == []
    
    def test_rollback_complete_status_returns_failed(self, discovery_service):
        """Test ROLLBACK_COMPLETE status returns FAILED."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("backend-storage", "ROLLBACK_COMPLETE"),
        ]
        stack_types_found = {"backend-storage"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.FAILED
        assert missing == []
    
    def test_rollback_failed_status_returns_failed(self, discovery_service):
        """Test ROLLBACK_FAILED status returns FAILED."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("backend-network", "ROLLBACK_FAILED"),
        ]
        stack_types_found = {"backend-network"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.FAILED
        assert missing == []
    
    def test_update_rollback_complete_status_returns_failed(self, discovery_service):
        """Test UPDATE_ROLLBACK_COMPLETE status returns FAILED."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("backend-domain", "UPDATE_ROLLBACK_COMPLETE"),
        ]
        stack_types_found = {"backend-domain"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.FAILED
        assert missing == []
    
    def test_update_rollback_failed_status_returns_failed(self, discovery_service):
        """Test UPDATE_ROLLBACK_FAILED status returns FAILED."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("frontend-global", "UPDATE_ROLLBACK_FAILED"),
        ]
        stack_types_found = {"frontend-global"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.FAILED
        assert missing == []
    
    def test_failed_takes_priority_over_in_progress(self, discovery_service):
        """Test FAILED status takes priority over IN_PROGRESS status."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("backend-foundation", "CREATE_COMPLETE"),
            self._create_stack("backend-iam-roles", "CREATE_IN_PROGRESS"),
            self._create_stack("backend-storage", "CREATE_FAILED"),
        ]
        stack_types_found = {"backend-foundation", "backend-iam-roles", "backend-storage"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.FAILED
        assert missing == []
    
    def test_failed_takes_priority_over_healthy(self, discovery_service):
        """Test FAILED status takes priority over HEALTHY status."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("frontend-global", "CREATE_COMPLETE"),
            self._create_stack("frontend-cognito", "CREATE_COMPLETE"),
            self._create_stack("frontend-regional", "ROLLBACK_COMPLETE"),
        ]
        stack_types_found = {"frontend-global", "frontend-cognito", "frontend-regional"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.FAILED
        assert missing == []
    
    def test_rollback_in_progress_returns_failed(self, discovery_service):
        """Test ROLLBACK_IN_PROGRESS status returns FAILED (contains ROLLBACK)."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("backend-service", "ROLLBACK_IN_PROGRESS"),
        ]
        stack_types_found = {"backend-service"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        # ROLLBACK_IN_PROGRESS contains "ROLLBACK" so it should be FAILED
        assert status == CapabilityStatus.FAILED
        assert missing == []
    
    def test_update_rollback_in_progress_returns_failed(self, discovery_service):
        """Test UPDATE_ROLLBACK_IN_PROGRESS status returns FAILED (contains ROLLBACK)."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("backend-network", "UPDATE_ROLLBACK_IN_PROGRESS"),
        ]
        stack_types_found = {"backend-network"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        # UPDATE_ROLLBACK_IN_PROGRESS contains "ROLLBACK" so it should be FAILED
        assert status == CapabilityStatus.FAILED
        assert missing == []


class TestDetermineCapabilityStatusInProgress:
    """
    **Feature: capability-discovery, Requirement 5.4: In Progress Status Detection**
    
    Tests that IN_PROGRESS status is correctly detected.
    When any stack is in an IN_PROGRESS state, mark the capability as "In Progress".
    
    **Validates: Requirement 5.4**
    """
    
    @pytest.fixture
    def discovery_service(self):
        """Create a DiscoveryService instance for testing."""
        return DiscoveryService(region="us-east-1")
    
    def _create_stack(self, stack_type: str, status: str) -> "DiscoveredStack":
        """Helper to create a DiscoveredStack for testing."""
        from app.services.discovery.models import DiscoveredStack
        return DiscoveredStack(
            stack_name=f"TestCapability-prod-{stack_type}",
            stack_type=stack_type,
            stack_status=status,
            region="us-east-1",
        )
    
    def test_create_in_progress_status_returns_in_progress(self, discovery_service):
        """Test CREATE_IN_PROGRESS status returns IN_PROGRESS."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("backend-foundation", "CREATE_IN_PROGRESS"),
        ]
        stack_types_found = {"backend-foundation"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.IN_PROGRESS
        assert missing == []
    
    def test_update_in_progress_status_returns_in_progress(self, discovery_service):
        """Test UPDATE_IN_PROGRESS status returns IN_PROGRESS."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("backend-service", "UPDATE_IN_PROGRESS"),
        ]
        stack_types_found = {"backend-service"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.IN_PROGRESS
        assert missing == []
    
    def test_delete_in_progress_status_returns_in_progress(self, discovery_service):
        """Test DELETE_IN_PROGRESS status returns IN_PROGRESS."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("backend-storage", "DELETE_IN_PROGRESS"),
        ]
        stack_types_found = {"backend-storage"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.IN_PROGRESS
        assert missing == []
    
    def test_import_in_progress_status_returns_in_progress(self, discovery_service):
        """Test IMPORT_IN_PROGRESS status returns IN_PROGRESS."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("backend-network", "IMPORT_IN_PROGRESS"),
        ]
        stack_types_found = {"backend-network"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.IN_PROGRESS
        assert missing == []
    
    def test_in_progress_takes_priority_over_partial(self, discovery_service):
        """Test IN_PROGRESS status takes priority over PARTIAL status."""
        from app.services.discovery.models import CapabilityStatus
        
        # Only some backend stacks present (would be PARTIAL), but one is in progress
        stacks = [
            self._create_stack("backend-foundation", "CREATE_COMPLETE"),
            self._create_stack("backend-iam-roles", "CREATE_IN_PROGRESS"),
        ]
        stack_types_found = {"backend-foundation", "backend-iam-roles"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.IN_PROGRESS
        assert missing == []
    
    def test_in_progress_takes_priority_over_healthy(self, discovery_service):
        """Test IN_PROGRESS status takes priority over HEALTHY status."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("frontend-global", "CREATE_COMPLETE"),
            self._create_stack("frontend-cognito", "UPDATE_COMPLETE"),
            self._create_stack("frontend-regional", "UPDATE_IN_PROGRESS"),
        ]
        stack_types_found = {"frontend-global", "frontend-cognito", "frontend-regional"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.IN_PROGRESS
        assert missing == []
    
    def test_multiple_in_progress_stacks(self, discovery_service):
        """Test multiple stacks in progress still returns IN_PROGRESS."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("backend-foundation", "CREATE_IN_PROGRESS"),
            self._create_stack("backend-iam-roles", "CREATE_IN_PROGRESS"),
            self._create_stack("backend-storage", "CREATE_IN_PROGRESS"),
        ]
        stack_types_found = {"backend-foundation", "backend-iam-roles", "backend-storage"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.IN_PROGRESS
        assert missing == []


class TestDetermineCapabilityStatusPartial:
    """
    **Feature: capability-discovery, Requirement 5.5: Partial Status Detection**
    
    Tests that PARTIAL status is correctly detected when stacks are missing.
    When stacks are partially deployed, mark the capability as "Partial" and list missing stack types.
    
    **Validates: Requirement 5.5**
    """
    
    @pytest.fixture
    def discovery_service(self):
        """Create a DiscoveryService instance for testing."""
        return DiscoveryService(region="us-east-1")
    
    def _create_stack(self, stack_type: str, status: str = "CREATE_COMPLETE") -> "DiscoveredStack":
        """Helper to create a DiscoveredStack for testing."""
        from app.services.discovery.models import DiscoveredStack
        return DiscoveredStack(
            stack_name=f"TestCapability-prod-{stack_type}",
            stack_type=stack_type,
            stack_status=status,
            region="us-east-1",
        )
    
    def test_partial_frontend_missing_cognito(self, discovery_service):
        """Test PARTIAL status when frontend-cognito is missing."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("frontend-global"),
            self._create_stack("frontend-regional"),
        ]
        stack_types_found = {"frontend-global", "frontend-regional"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.PARTIAL
        assert "frontend-cognito" in missing
    
    def test_partial_frontend_missing_regional(self, discovery_service):
        """Test PARTIAL status when frontend-regional is missing."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("frontend-global"),
            self._create_stack("frontend-cognito"),
        ]
        stack_types_found = {"frontend-global", "frontend-cognito"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.PARTIAL
        assert "frontend-regional" in missing
    
    def test_partial_frontend_missing_global(self, discovery_service):
        """Test PARTIAL status when frontend-global is missing."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("frontend-cognito"),
            self._create_stack("frontend-regional"),
        ]
        stack_types_found = {"frontend-cognito", "frontend-regional"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.PARTIAL
        assert "frontend-global" in missing
    
    def test_partial_backend_missing_service(self, discovery_service):
        """Test PARTIAL status when backend-service is missing."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("backend-foundation"),
            self._create_stack("backend-iam-roles"),
            self._create_stack("backend-storage"),
            self._create_stack("backend-network"),
            self._create_stack("backend-domain"),
        ]
        stack_types_found = {"backend-foundation", "backend-iam-roles", "backend-storage", "backend-network", "backend-domain"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.PARTIAL
        assert "backend-service" in missing
    
    def test_partial_backend_missing_multiple_stacks(self, discovery_service):
        """Test PARTIAL status when multiple backend stacks are missing."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("backend-foundation"),
            self._create_stack("backend-iam-roles"),
        ]
        stack_types_found = {"backend-foundation", "backend-iam-roles"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.PARTIAL
        # Should be missing several backend stacks
        assert len(missing) > 0
        # Check some expected missing stacks
        assert "backend-storage" in missing or "backend-network" in missing or "backend-service" in missing
    
    def test_partial_mixed_frontend_backend_missing_stacks(self, discovery_service):
        """Test PARTIAL status with mixed frontend and backend, some missing."""
        from app.services.discovery.models import CapabilityStatus
        
        # Has some frontend and some backend, but not all of either
        stacks = [
            self._create_stack("frontend-global"),
            self._create_stack("backend-foundation"),
            self._create_stack("backend-iam-roles"),
        ]
        stack_types_found = {"frontend-global", "backend-foundation", "backend-iam-roles"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.PARTIAL
        # Should be missing frontend stacks (cognito, regional) and backend stacks
        assert len(missing) > 0
    
    def test_partial_returns_sorted_missing_stacks(self, discovery_service):
        """Test that missing stacks list is sorted."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("frontend-regional"),
        ]
        stack_types_found = {"frontend-regional"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.PARTIAL
        # Missing list should be sorted
        assert missing == sorted(missing)


class TestDetermineCapabilityStatusHealthy:
    """
    **Feature: capability-discovery, Requirement 5.2: Healthy Status Detection**
    
    Tests that HEALTHY status is correctly detected when all stacks are complete.
    When all stacks are in CREATE_COMPLETE or UPDATE_COMPLETE state, mark the capability as "Healthy".
    
    **Validates: Requirement 5.2**
    """
    
    @pytest.fixture
    def discovery_service(self):
        """Create a DiscoveryService instance for testing."""
        return DiscoveryService(region="us-east-1")
    
    def _create_stack(self, stack_type: str, status: str = "CREATE_COMPLETE") -> "DiscoveredStack":
        """Helper to create a DiscoveredStack for testing."""
        from app.services.discovery.models import DiscoveredStack
        return DiscoveredStack(
            stack_name=f"TestCapability-prod-{stack_type}",
            stack_type=stack_type,
            stack_status=status,
            region="us-east-1",
        )
    
    def test_all_frontend_stacks_create_complete_returns_healthy(self, discovery_service):
        """Test HEALTHY status when all frontend stacks are CREATE_COMPLETE."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("frontend-global", "CREATE_COMPLETE"),
            self._create_stack("frontend-cognito", "CREATE_COMPLETE"),
            self._create_stack("frontend-regional", "CREATE_COMPLETE"),
        ]
        stack_types_found = {"frontend-global", "frontend-cognito", "frontend-regional"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.HEALTHY
        assert missing == []
    
    def test_all_frontend_stacks_update_complete_returns_healthy(self, discovery_service):
        """Test HEALTHY status when all frontend stacks are UPDATE_COMPLETE."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("frontend-global", "UPDATE_COMPLETE"),
            self._create_stack("frontend-cognito", "UPDATE_COMPLETE"),
            self._create_stack("frontend-regional", "UPDATE_COMPLETE"),
        ]
        stack_types_found = {"frontend-global", "frontend-cognito", "frontend-regional"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.HEALTHY
        assert missing == []
    
    def test_mixed_create_update_complete_returns_healthy(self, discovery_service):
        """Test HEALTHY status with mix of CREATE_COMPLETE and UPDATE_COMPLETE."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("frontend-global", "CREATE_COMPLETE"),
            self._create_stack("frontend-cognito", "UPDATE_COMPLETE"),
            self._create_stack("frontend-regional", "CREATE_COMPLETE"),
        ]
        stack_types_found = {"frontend-global", "frontend-cognito", "frontend-regional"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.HEALTHY
        assert missing == []
    
    def test_all_backend_stacks_complete_returns_healthy(self, discovery_service):
        """Test HEALTHY status when all backend stacks are complete."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("backend-foundation", "CREATE_COMPLETE"),
            self._create_stack("backend-iam-roles", "CREATE_COMPLETE"),
            self._create_stack("backend-regional-cert", "CREATE_COMPLETE"),
            self._create_stack("backend-storage", "CREATE_COMPLETE"),
            self._create_stack("backend-network", "CREATE_COMPLETE"),
            self._create_stack("backend-service", "CREATE_COMPLETE"),
            self._create_stack("backend-domain", "CREATE_COMPLETE"),
        ]
        stack_types_found = {
            "backend-foundation", "backend-iam-roles", "backend-regional-cert",
            "backend-storage", "backend-network", "backend-service", "backend-domain"
        }
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.HEALTHY
        assert missing == []
    
    def test_full_stack_frontend_and_backend_returns_healthy(self, discovery_service):
        """Test HEALTHY status when all frontend and backend stacks are complete."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            # Frontend stacks
            self._create_stack("frontend-global", "CREATE_COMPLETE"),
            self._create_stack("frontend-cognito", "CREATE_COMPLETE"),
            self._create_stack("frontend-regional", "CREATE_COMPLETE"),
            # Backend stacks
            self._create_stack("backend-foundation", "CREATE_COMPLETE"),
            self._create_stack("backend-iam-roles", "CREATE_COMPLETE"),
            self._create_stack("backend-regional-cert", "CREATE_COMPLETE"),
            self._create_stack("backend-storage", "CREATE_COMPLETE"),
            self._create_stack("backend-network", "CREATE_COMPLETE"),
            self._create_stack("backend-service", "CREATE_COMPLETE"),
            self._create_stack("backend-domain", "CREATE_COMPLETE"),
        ]
        stack_types_found = {
            "frontend-global", "frontend-cognito", "frontend-regional",
            "backend-foundation", "backend-iam-roles", "backend-regional-cert",
            "backend-storage", "backend-network", "backend-service", "backend-domain"
        }
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.HEALTHY
        assert missing == []
    
    def test_import_complete_returns_healthy(self, discovery_service):
        """Test HEALTHY status with IMPORT_COMPLETE status (no FAILED or IN_PROGRESS)."""
        from app.services.discovery.models import CapabilityStatus
        
        stacks = [
            self._create_stack("frontend-global", "IMPORT_COMPLETE"),
            self._create_stack("frontend-cognito", "IMPORT_COMPLETE"),
            self._create_stack("frontend-regional", "IMPORT_COMPLETE"),
        ]
        stack_types_found = {"frontend-global", "frontend-cognito", "frontend-regional"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.HEALTHY
        assert missing == []


class TestDetermineCapabilityStatusPriority:
    """
    **Feature: capability-discovery, Requirements 5.2, 5.3, 5.4, 5.5: Status Priority**
    
    Tests the priority order: FAILED > IN_PROGRESS > PARTIAL > HEALTHY
    
    **Validates: Requirements 5.2, 5.3, 5.4, 5.5**
    """
    
    @pytest.fixture
    def discovery_service(self):
        """Create a DiscoveryService instance for testing."""
        return DiscoveryService(region="us-east-1")
    
    def _create_stack(self, stack_type: str, status: str = "CREATE_COMPLETE") -> "DiscoveredStack":
        """Helper to create a DiscoveredStack for testing."""
        from app.services.discovery.models import DiscoveredStack
        return DiscoveredStack(
            stack_name=f"TestCapability-prod-{stack_type}",
            stack_type=stack_type,
            stack_status=status,
            region="us-east-1",
        )
    
    def test_failed_highest_priority(self, discovery_service):
        """Test FAILED has highest priority over all other statuses."""
        from app.services.discovery.models import CapabilityStatus
        
        # Mix of FAILED, IN_PROGRESS, and COMPLETE - FAILED should win
        stacks = [
            self._create_stack("frontend-global", "CREATE_COMPLETE"),
            self._create_stack("frontend-cognito", "CREATE_IN_PROGRESS"),
            self._create_stack("frontend-regional", "CREATE_FAILED"),
        ]
        stack_types_found = {"frontend-global", "frontend-cognito", "frontend-regional"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.FAILED
    
    def test_in_progress_over_partial(self, discovery_service):
        """Test IN_PROGRESS has priority over PARTIAL."""
        from app.services.discovery.models import CapabilityStatus
        
        # Missing stacks (would be PARTIAL) but one is IN_PROGRESS
        stacks = [
            self._create_stack("frontend-global", "CREATE_COMPLETE"),
            self._create_stack("frontend-cognito", "CREATE_IN_PROGRESS"),
            # frontend-regional is missing
        ]
        stack_types_found = {"frontend-global", "frontend-cognito"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.IN_PROGRESS
    
    def test_in_progress_over_healthy(self, discovery_service):
        """Test IN_PROGRESS has priority over HEALTHY."""
        from app.services.discovery.models import CapabilityStatus
        
        # All stacks present but one is IN_PROGRESS
        stacks = [
            self._create_stack("frontend-global", "CREATE_COMPLETE"),
            self._create_stack("frontend-cognito", "CREATE_COMPLETE"),
            self._create_stack("frontend-regional", "UPDATE_IN_PROGRESS"),
        ]
        stack_types_found = {"frontend-global", "frontend-cognito", "frontend-regional"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.IN_PROGRESS
    
    def test_partial_over_healthy(self, discovery_service):
        """Test PARTIAL has priority over HEALTHY (when stacks are missing)."""
        from app.services.discovery.models import CapabilityStatus
        
        # All present stacks are COMPLETE but some are missing
        stacks = [
            self._create_stack("frontend-global", "CREATE_COMPLETE"),
            self._create_stack("frontend-cognito", "CREATE_COMPLETE"),
            # frontend-regional is missing
        ]
        stack_types_found = {"frontend-global", "frontend-cognito"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.PARTIAL
        assert "frontend-regional" in missing
    
    def test_healthy_lowest_priority(self, discovery_service):
        """Test HEALTHY only when no failures, no in-progress, and no missing stacks."""
        from app.services.discovery.models import CapabilityStatus
        
        # All stacks present and complete
        stacks = [
            self._create_stack("frontend-global", "CREATE_COMPLETE"),
            self._create_stack("frontend-cognito", "UPDATE_COMPLETE"),
            self._create_stack("frontend-regional", "CREATE_COMPLETE"),
        ]
        stack_types_found = {"frontend-global", "frontend-cognito", "frontend-regional"}
        
        status, missing = discovery_service._determine_capability_status(stacks, stack_types_found)
        
        assert status == CapabilityStatus.HEALTHY
        assert missing == []
