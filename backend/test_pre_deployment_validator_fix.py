"""
Unit tests for PreDeploymentValidator orphaned resource detection fix

Tests verify that:
1. Stable stacks skip orphaned detection
2. Non-existent stacks trigger orphaned detection
3. Unstable stack deletion skips orphaned detection
4. Logging messages are correct for each scenario
"""
import pytest
from unittest.mock import Mock, MagicMock, patch, call
from app.services.pre_deployment_validator import PreDeploymentValidator
from app.models.validation import StackStatus, ValidationReport


class TestPreDeploymentValidatorFix:
    """Test suite for PreDeploymentValidator orphaned resource detection fix"""
    
    @pytest.fixture
    def validator(self):
        """Create a PreDeploymentValidator instance for testing"""
        return PreDeploymentValidator(credentials={})
    
    @pytest.fixture
    def mock_config(self):
        """Create a mock deployment configuration"""
        return {
            'capability_name': 'test-capability',
            'environment': 'dev',
            'region': 'us-east-1',
            'infrastructure': {},
            'source': {},
            'tags': {}
        }
    
    def test_stable_stack_skips_orphaned_detection(self, validator, mock_config):
        """
        Test that stable stacks skip orphaned resource detection
        
        Validates: Requirements 1.1, 1.5
        """
        # Mock dependencies
        with patch.object(validator, 'check_stack_status') as mock_check_status, \
             patch.object(validator, 'detect_orphaned_resources') as mock_detect, \
             patch('app.services.pre_deployment_validator.CloudFormationDeploymentService') as mock_cf_service:
            
            # Setup mocks
            mock_check_status.return_value = StackStatus.STABLE
            mock_cf_instance = Mock()
            mock_cf_instance.STACK_ORDER = ['frontend-regional']
            mock_cf_instance.get_stack_name.return_value = 'test-capability-dev-frontend-regional'
            mock_cf_service.return_value = mock_cf_instance
            
            # Execute validation
            callback = Mock()
            report = validator.validate_deployment(
                mock_config,
                deploy_frontend=True,
                deploy_backend=False,
                callback=callback
            )
            
            # Assertions
            # 1. Orphaned resource detection should NOT be called
            mock_detect.assert_not_called()
            
            # 2. Validation should succeed (no issues found)
            assert report.success is True
            assert len(report.issues_found) == 0
            
            # 3. Callback should indicate stable stack was skipped
            callback_messages = [str(call_args[0][0]) for call_args in callback.call_args_list]
            assert any('stable' in msg.lower() and 'skipping' in msg.lower() for msg in callback_messages)
    
    def test_non_existent_stack_triggers_orphaned_detection(self, validator, mock_config):
        """
        Test that non-existent stacks trigger orphaned resource detection
        
        Validates: Requirements 1.2
        """
        # Mock dependencies
        with patch.object(validator, 'check_stack_status') as mock_check_status, \
             patch.object(validator, 'detect_orphaned_resources') as mock_detect, \
             patch.object(validator, 'cleanup_orphaned_resources') as mock_cleanup, \
             patch('app.services.pre_deployment_validator.CloudFormationDeploymentService') as mock_cf_service:
            
            # Setup mocks
            mock_check_status.return_value = StackStatus.NOT_EXISTS
            mock_detect.return_value = []  # No orphaned resources found
            mock_cleanup.return_value = []
            
            mock_cf_instance = Mock()
            mock_cf_instance.STACK_ORDER = ['frontend-regional']
            mock_cf_instance.get_stack_name.return_value = 'test-capability-dev-frontend-regional'
            mock_cf_instance.load_template.return_value = 'template_body'
            mock_cf_instance.build_parameters.return_value = []
            mock_cf_service.return_value = mock_cf_instance
            
            # Execute validation
            callback = Mock()
            report = validator.validate_deployment(
                mock_config,
                deploy_frontend=True,
                deploy_backend=False,
                callback=callback
            )
            
            # Assertions
            # 1. Orphaned resource detection SHOULD be called
            mock_detect.assert_called_once()
            
            # 2. Validation should succeed (no issues found)
            assert report.success is True
            
            # 3. Callback should indicate checking for orphaned resources
            callback_messages = [str(call_args[0][0]) for call_args in callback.call_args_list]
            assert any('does not exist' in msg.lower() and 'checking' in msg.lower() for msg in callback_messages)
    
    def test_unstable_stack_deletion_skips_orphaned_detection(self, validator, mock_config):
        """
        Test that unstable stack deletion skips orphaned resource detection
        
        Validates: Requirements 1.3
        """
        # Mock dependencies
        with patch.object(validator, 'check_stack_status') as mock_check_status, \
             patch.object(validator, 'cleanup_unstable_stack') as mock_cleanup_stack, \
             patch.object(validator, 'detect_orphaned_resources') as mock_detect, \
             patch('app.services.pre_deployment_validator.CloudFormationDeploymentService') as mock_cf_service:
            
            # Setup mocks
            mock_check_status.return_value = StackStatus.UNSTABLE
            mock_cleanup_stack.return_value = True  # Cleanup successful
            
            mock_cf_instance = Mock()
            mock_cf_instance.STACK_ORDER = ['frontend-regional']
            mock_cf_instance.get_stack_name.return_value = 'test-capability-dev-frontend-regional'
            mock_cf_service.return_value = mock_cf_instance
            
            # Execute validation
            callback = Mock()
            report = validator.validate_deployment(
                mock_config,
                deploy_frontend=True,
                deploy_backend=False,
                callback=callback
            )
            
            # Assertions
            # 1. Unstable stack cleanup SHOULD be called
            mock_cleanup_stack.assert_called_once()
            
            # 2. Orphaned resource detection should NOT be called
            mock_detect.assert_not_called()
            
            # 3. Validation should succeed (issue was resolved)
            assert report.success is True
            assert len(report.issues_resolved) == 1
            
            # 4. Callback should indicate unstable stack was cleaned and orphaned check skipped
            callback_messages = [str(call_args[0][0]) for call_args in callback.call_args_list]
            assert any('cleaned up unstable stack' in msg.lower() and 'skipping' in msg.lower() for msg in callback_messages)
    
    def test_logging_for_stable_stack(self, validator, mock_config, caplog):
        """
        Test that logging messages are correct for stable stacks
        
        Validates: Requirements 2.1
        """
        import logging
        caplog.set_level(logging.INFO)
        
        # Mock dependencies
        with patch.object(validator, 'check_stack_status') as mock_check_status, \
             patch('app.services.pre_deployment_validator.CloudFormationDeploymentService') as mock_cf_service:
            
            # Setup mocks
            mock_check_status.return_value = StackStatus.STABLE
            
            mock_cf_instance = Mock()
            mock_cf_instance.STACK_ORDER = ['frontend-regional']
            mock_cf_instance.get_stack_name.return_value = 'test-capability-dev-frontend-regional'
            mock_cf_service.return_value = mock_cf_instance
            
            # Execute validation
            validator.validate_deployment(
                mock_config,
                deploy_frontend=True,
                deploy_backend=False
            )
            
            # Assertions - check log messages
            log_messages = [record.message for record in caplog.records]
            assert any('STABLE' in msg and 'skipping orphaned resource check' in msg for msg in log_messages)
    
    def test_logging_for_unstable_stack(self, validator, mock_config, caplog):
        """
        Test that logging messages are correct for unstable stacks
        
        Validates: Requirements 2.2
        """
        import logging
        caplog.set_level(logging.INFO)
        
        # Mock dependencies
        with patch.object(validator, 'check_stack_status') as mock_check_status, \
             patch.object(validator, 'cleanup_unstable_stack') as mock_cleanup_stack, \
             patch('app.services.pre_deployment_validator.CloudFormationDeploymentService') as mock_cf_service:
            
            # Setup mocks
            mock_check_status.return_value = StackStatus.UNSTABLE
            mock_cleanup_stack.return_value = True
            
            mock_cf_instance = Mock()
            mock_cf_instance.STACK_ORDER = ['frontend-regional']
            mock_cf_instance.get_stack_name.return_value = 'test-capability-dev-frontend-regional'
            mock_cf_service.return_value = mock_cf_instance
            
            # Execute validation
            validator.validate_deployment(
                mock_config,
                deploy_frontend=True,
                deploy_backend=False
            )
            
            # Assertions - check log messages
            log_messages = [record.message for record in caplog.records]
            assert any('UNSTABLE' in msg and 'will delete and skip orphaned check' in msg for msg in log_messages)
            assert any('Skipping orphaned resource check' in msg and 'stack deletion handles cleanup' in msg for msg in log_messages)
    
    def test_logging_for_non_existent_stack(self, validator, mock_config, caplog):
        """
        Test that logging messages are correct for non-existent stacks
        
        Validates: Requirements 2.3
        """
        import logging
        caplog.set_level(logging.INFO)
        
        # Mock dependencies
        with patch.object(validator, 'check_stack_status') as mock_check_status, \
             patch.object(validator, 'detect_orphaned_resources') as mock_detect, \
             patch.object(validator, 'cleanup_orphaned_resources') as mock_cleanup, \
             patch('app.services.pre_deployment_validator.CloudFormationDeploymentService') as mock_cf_service:
            
            # Setup mocks
            mock_check_status.return_value = StackStatus.NOT_EXISTS
            mock_detect.return_value = []
            mock_cleanup.return_value = []
            
            mock_cf_instance = Mock()
            mock_cf_instance.STACK_ORDER = ['frontend-regional']
            mock_cf_instance.get_stack_name.return_value = 'test-capability-dev-frontend-regional'
            mock_cf_instance.load_template.return_value = 'template_body'
            mock_cf_instance.build_parameters.return_value = []
            mock_cf_service.return_value = mock_cf_instance
            
            # Execute validation
            validator.validate_deployment(
                mock_config,
                deploy_frontend=True,
                deploy_backend=False
            )
            
            # Assertions - check log messages
            log_messages = [record.message for record in caplog.records]
            assert any('does NOT exist' in msg and 'checking for orphaned resources' in msg for msg in log_messages)
    
    def test_in_progress_stack_skips_orphaned_detection(self, validator, mock_config):
        """
        Test that IN_PROGRESS stacks skip orphaned resource detection
        
        This is an edge case to ensure we don't interfere with ongoing operations
        """
        # Mock dependencies
        with patch.object(validator, 'check_stack_status') as mock_check_status, \
             patch.object(validator, 'detect_orphaned_resources') as mock_detect, \
             patch('app.services.pre_deployment_validator.CloudFormationDeploymentService') as mock_cf_service:
            
            # Setup mocks
            mock_check_status.return_value = StackStatus.IN_PROGRESS
            
            mock_cf_instance = Mock()
            mock_cf_instance.STACK_ORDER = ['frontend-regional']
            mock_cf_instance.get_stack_name.return_value = 'test-capability-dev-frontend-regional'
            mock_cf_service.return_value = mock_cf_instance
            
            # Execute validation
            callback = Mock()
            report = validator.validate_deployment(
                mock_config,
                deploy_frontend=True,
                deploy_backend=False,
                callback=callback
            )
            
            # Assertions
            # 1. Orphaned resource detection should NOT be called
            mock_detect.assert_not_called()
            
            # 2. Validation should succeed (no issues found)
            assert report.success is True
            
            # 3. Callback should indicate in-progress stack was skipped
            callback_messages = [str(call_args[0][0]) for call_args in callback.call_args_list]
            assert any('in progress' in msg.lower() and 'skipping' in msg.lower() for msg in callback_messages)
