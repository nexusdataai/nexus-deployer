"""
Unit tests for DeploymentOrchestrator strategy-aware validation

Tests verify that:
1. CLEAN_DEPLOY strategy skips validation
2. UPDATE_EXISTING strategy runs validation
3. Logging messages are correct for each strategy
"""
import pytest
from unittest.mock import Mock, MagicMock, patch, call
from app.services.deployment_orchestrator import DeploymentOrchestrator
from app.models.stack_detection import DeploymentStrategy
from app.models.validation import ValidationReport


class TestDeploymentOrchestratorFix:
    """Test suite for DeploymentOrchestrator validation skip logic"""
    
    @pytest.fixture
    def orchestrator(self):
        """Create a DeploymentOrchestrator instance for testing"""
        return DeploymentOrchestrator(credentials={})
    
    @pytest.fixture
    def mock_config(self):
        """Create a mock deployment configuration"""
        return {
            'capability': {'name': 'test-capability'},
            'target': {'environment': 'dev', 'region': 'us-east-1'},
            'infrastructure': {},
            'source': {},
            'tags': {},
            'deployment': {'pre_validation': {'enabled': True}}
        }
    
    def test_clean_deploy_skips_validation(self, orchestrator, mock_config):
        """
        Test that CLEAN_DEPLOY strategy skips pre-deployment validation
        
        Validates: Requirements 1.4, 4.1
        """
        # Mock dependencies
        with patch.object(orchestrator, 'cleanup_capability') as mock_cleanup, \
             patch.object(orchestrator, 'deploy_capability') as mock_deploy, \
             patch.object(orchestrator.validator, 'validate_deployment') as mock_validate:
            
            # Setup mocks
            mock_cleanup.return_value = {
                'success': True,
                'stacks': {},
                'summary': 'Cleanup successful'
            }
            mock_deploy.return_value = {
                'success': True,
                'capability_name': 'test-capability',
                'environment': 'dev',
                'region': 'us-east-1'
            }
            
            # Execute deployment with CLEAN_DEPLOY strategy
            callback = Mock()
            result = orchestrator.deploy_capability_with_strategy(
                mock_config,
                DeploymentStrategy.CLEAN_DEPLOY,
                deploy_frontend=True,
                deploy_backend=False,
                callback=callback
            )
            
            # Assertions
            # 1. Validation should NOT be called
            mock_validate.assert_not_called()
            
            # 2. deploy_capability should be called with skip_validation=True
            mock_deploy.assert_called_once()
            call_kwargs = mock_deploy.call_args[1]
            assert call_kwargs.get('skip_validation') is True
            
            # 3. Callback should indicate validation is skipped
            callback_messages = [str(call_args[0][0]) for call_args in callback.call_args_list]
            assert any('skipping pre-deployment validation' in msg.lower() for msg in callback_messages)
            
            # 4. Result should indicate CLEAN_DEPLOY strategy
            assert result.get('strategy') == DeploymentStrategy.CLEAN_DEPLOY.value
    
    def test_update_existing_runs_validation(self, orchestrator, mock_config):
        """
        Test that UPDATE_EXISTING strategy runs pre-deployment validation
        
        Validates: Requirements 4.2
        """
        # Mock dependencies
        with patch.object(orchestrator, 'deploy_capability') as mock_deploy, \
             patch.object(orchestrator.validator, 'validate_deployment') as mock_validate:
            
            # Setup mocks
            mock_validate.return_value = ValidationReport(
                success=True,
                issues_found=[],
                issues_resolved=[],
                issues_unresolved=[],
                validation_time=1.0,
                summary="Validation successful"
            )
            mock_deploy.return_value = {
                'success': True,
                'capability_name': 'test-capability',
                'environment': 'dev',
                'region': 'us-east-1'
            }
            
            # Execute deployment with UPDATE_EXISTING strategy
            callback = Mock()
            result = orchestrator.deploy_capability_with_strategy(
                mock_config,
                DeploymentStrategy.UPDATE_EXISTING,
                deploy_frontend=True,
                deploy_backend=False,
                callback=callback
            )
            
            # Assertions
            # 1. deploy_capability should be called with skip_validation=False
            mock_deploy.assert_called_once()
            call_kwargs = mock_deploy.call_args[1]
            assert call_kwargs.get('skip_validation') is False
            
            # 2. Result should indicate UPDATE_EXISTING strategy
            assert result.get('strategy') == DeploymentStrategy.UPDATE_EXISTING.value
    
    def test_deploy_capability_with_skip_validation_true(self, orchestrator, mock_config):
        """
        Test that deploy_capability skips validation when skip_validation=True
        
        Validates: Requirements 4.1, 4.4
        """
        # Mock dependencies
        with patch.object(orchestrator.validator, 'validate_deployment') as mock_validate, \
             patch.object(orchestrator.cfn_service, '_get_client') as mock_get_client, \
             patch.object(orchestrator.cfn_service, 'STACK_ORDER', []):
            
            # Setup mocks
            mock_cfn_client = Mock()
            mock_get_client.return_value = mock_cfn_client
            
            # Execute deployment with skip_validation=True
            callback = Mock()
            result = orchestrator.deploy_capability(
                mock_config,
                deploy_frontend=False,
                deploy_backend=False,
                callback=callback,
                skip_validation=True
            )
            
            # Assertions
            # 1. Validation should NOT be called
            mock_validate.assert_not_called()
            
            # 2. Callback should indicate validation is skipped
            callback_messages = [str(call_args[0][0]) for call_args in callback.call_args_list]
            assert any('skipping pre-deployment validation' in msg.lower() for msg in callback_messages)
    
    def test_deploy_capability_with_skip_validation_false(self, orchestrator, mock_config):
        """
        Test that deploy_capability runs validation when skip_validation=False
        
        Validates: Requirements 4.2, 4.4
        """
        # Mock dependencies
        with patch.object(orchestrator.validator, 'validate_deployment') as mock_validate, \
             patch.object(orchestrator.cfn_service, '_get_client') as mock_get_client, \
             patch.object(orchestrator.cfn_service, 'STACK_ORDER', []):
            
            # Setup mocks
            mock_validate.return_value = ValidationReport(
                success=True,
                issues_found=[],
                issues_resolved=[],
                issues_unresolved=[],
                validation_time=1.0,
                summary="Validation successful"
            )
            mock_cfn_client = Mock()
            mock_get_client.return_value = mock_cfn_client
            
            # Execute deployment with skip_validation=False
            callback = Mock()
            result = orchestrator.deploy_capability(
                mock_config,
                deploy_frontend=False,
                deploy_backend=False,
                callback=callback,
                skip_validation=False
            )
            
            # Assertions
            # 1. Validation SHOULD be called
            mock_validate.assert_called_once()
            
            # 2. Callback should indicate validation is running
            callback_messages = [str(call_args[0][0]) for call_args in callback.call_args_list]
            assert any('running pre-deployment validation' in msg.lower() for msg in callback_messages)
    
    def test_deploy_capability_default_runs_validation(self, orchestrator, mock_config):
        """
        Test that deploy_capability runs validation by default (skip_validation not specified)
        
        Validates: Requirements 4.4
        """
        # Mock dependencies
        with patch.object(orchestrator.validator, 'validate_deployment') as mock_validate, \
             patch.object(orchestrator.cfn_service, '_get_client') as mock_get_client, \
             patch.object(orchestrator.cfn_service, 'STACK_ORDER', []):
            
            # Setup mocks
            mock_validate.return_value = ValidationReport(
                success=True,
                issues_found=[],
                issues_resolved=[],
                issues_unresolved=[],
                validation_time=1.0,
                summary="Validation successful"
            )
            mock_cfn_client = Mock()
            mock_get_client.return_value = mock_cfn_client
            
            # Execute deployment without skip_validation parameter (default behavior)
            callback = Mock()
            result = orchestrator.deploy_capability(
                mock_config,
                deploy_frontend=False,
                deploy_backend=False,
                callback=callback
                # Note: skip_validation not specified, should default to False
            )
            
            # Assertions
            # 1. Validation SHOULD be called (default behavior)
            mock_validate.assert_called_once()
    
    def test_logging_for_clean_deploy(self, orchestrator, mock_config, caplog):
        """
        Test that logging messages are correct for CLEAN_DEPLOY strategy
        
        Validates: Requirements 2.4
        """
        import logging
        caplog.set_level(logging.INFO)
        
        # Mock dependencies
        with patch.object(orchestrator, 'cleanup_capability') as mock_cleanup, \
             patch.object(orchestrator, 'deploy_capability') as mock_deploy:
            
            # Setup mocks
            mock_cleanup.return_value = {
                'success': True,
                'stacks': {},
                'summary': 'Cleanup successful'
            }
            mock_deploy.return_value = {
                'success': True,
                'capability_name': 'test-capability',
                'environment': 'dev',
                'region': 'us-east-1'
            }
            
            # Execute deployment with CLEAN_DEPLOY strategy
            orchestrator.deploy_capability_with_strategy(
                mock_config,
                DeploymentStrategy.CLEAN_DEPLOY,
                deploy_frontend=True,
                deploy_backend=False
            )
            
            # Assertions - check log messages
            log_messages = [record.message for record in caplog.records]
            assert any('skipping pre-deployment validation' in msg.lower() and 'clean_deploy' in msg.lower() for msg in log_messages)
    
    def test_logging_for_skip_validation_parameter(self, orchestrator, mock_config, caplog):
        """
        Test that logging messages are correct when skip_validation parameter is used
        
        Validates: Requirements 2.4
        """
        import logging
        caplog.set_level(logging.INFO)
        
        # Mock dependencies
        with patch.object(orchestrator.cfn_service, '_get_client') as mock_get_client, \
             patch.object(orchestrator.cfn_service, 'STACK_ORDER', []):
            
            # Setup mocks
            mock_cfn_client = Mock()
            mock_get_client.return_value = mock_cfn_client
            
            # Execute deployment with skip_validation=True
            orchestrator.deploy_capability(
                mock_config,
                deploy_frontend=False,
                deploy_backend=False,
                skip_validation=True
            )
            
            # Assertions - check log messages
            log_messages = [record.message for record in caplog.records]
            assert any('skipping pre-deployment validation' in msg.lower() and 'skip_validation parameter is true' in msg.lower() for msg in log_messages)
