"""
Integration tests for stack detection service
Tests end-to-end detection with mocked CloudFormation responses
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from botocore.exceptions import ClientError

from app.services.stack_detection_service import StackDetectionService
from app.models.stack_detection import DeploymentStrategy


class TestStackDetectionIntegration:
    """Integration tests for stack detection"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.credentials = {
            'aws_access_key_id': 'test_key',
            'aws_secret_access_key': 'test_secret',
            'aws_session_token': 'test_token'
        }
        self.service = StackDetectionService(credentials=self.credentials)
    
    @patch('app.services.stack_detection_service.boto3.client')
    def test_detect_stacks_with_all_updatable(self, mock_boto_client):
        """Test detection with all stacks in updatable state"""
        # Mock CloudFormation responses
        mock_cfn = MagicMock()
        mock_boto_client.return_value = mock_cfn
        
        # Mock responses for each stack
        def describe_stacks_side_effect(StackName):
            if 'frontend-global' in StackName:
                return {
                    'Stacks': [{
                        'StackName': StackName,
                        'StackStatus': 'CREATE_COMPLETE',
                        'CreationTime': datetime.utcnow(),
                        'StackStatusReason': None
                    }]
                }
            elif 'backend-foundation' in StackName:
                return {
                    'Stacks': [{
                        'StackName': StackName,
                        'StackStatus': 'UPDATE_COMPLETE',
                        'CreationTime': datetime.utcnow(),
                        'LastUpdatedTime': datetime.utcnow(),
                        'StackStatusReason': None
                    }]
                }
            else:
                # Stack not found
                error = ClientError(
                    {'Error': {'Code': 'ValidationError', 'Message': 'Stack does not exist'}},
                    'describe_stacks'
                )
                raise error
        
        mock_cfn.describe_stacks.side_effect = describe_stacks_side_effect
        
        # Run detection
        result = self.service.detect_existing_stacks(
            capability_name='test-capability',
            environment='prod',
            region='us-west-2',
            deploy_frontend=True,
            deploy_backend=True
        )
        
        # Verify results
        assert result.capability_name == 'test-capability'
        assert result.environment == 'prod'
        assert result.region == 'us-west-2'
        assert result.has_existing_stacks == True
        assert result.has_failed_stacks == False
        assert result.has_in_progress_stacks == False
        assert result.is_updatable == True
        assert result.recommended_strategy == DeploymentStrategy.UPDATE_EXISTING
        assert "stable" in result.recommendation_reason.lower() or "updatable" in result.recommendation_reason.lower()
    
    @patch('app.services.stack_detection_service.boto3.client')
    def test_detect_stacks_with_failed_stack(self, mock_boto_client):
        """Test detection with a failed stack"""
        mock_cfn = MagicMock()
        mock_boto_client.return_value = mock_cfn
        
        def describe_stacks_side_effect(StackName):
            if 'frontend-global' in StackName:
                return {
                    'Stacks': [{
                        'StackName': StackName,
                        'StackStatus': 'ROLLBACK_COMPLETE',
                        'CreationTime': datetime.utcnow(),
                        'StackStatusReason': 'Resource creation failed'
                    }]
                }
            else:
                error = ClientError(
                    {'Error': {'Code': 'ValidationError', 'Message': 'Stack does not exist'}},
                    'describe_stacks'
                )
                raise error
        
        mock_cfn.describe_stacks.side_effect = describe_stacks_side_effect
        
        result = self.service.detect_existing_stacks(
            capability_name='test-capability',
            environment='prod',
            region='us-west-2',
            deploy_frontend=True,
            deploy_backend=False
        )
        
        assert result.has_failed_stacks == True
        assert result.is_updatable == False
        assert result.recommended_strategy == DeploymentStrategy.CLEAN_DEPLOY
        assert "failed" in result.recommendation_reason.lower()
    
    @patch('app.services.stack_detection_service.boto3.client')
    def test_detect_stacks_with_in_progress_stack(self, mock_boto_client):
        """Test detection with an in-progress stack"""
        mock_cfn = MagicMock()
        mock_boto_client.return_value = mock_cfn
        
        def describe_stacks_side_effect(StackName):
            return {
                'Stacks': [{
                    'StackName': StackName,
                    'StackStatus': 'UPDATE_IN_PROGRESS',
                    'CreationTime': datetime.utcnow(),
                    'StackStatusReason': None
                }]
            }
        
        mock_cfn.describe_stacks.side_effect = describe_stacks_side_effect
        
        result = self.service.detect_existing_stacks(
            capability_name='test-capability',
            environment='prod',
            region='us-west-2',
            deploy_frontend=True,
            deploy_backend=False
        )
        
        assert result.has_in_progress_stacks == True
        assert result.recommended_strategy is None
        assert "wait" in result.recommendation_reason.lower() or "in-progress" in result.recommendation_reason.lower()
    
    @patch('app.services.stack_detection_service.boto3.client')
    def test_detect_stacks_no_stacks_found(self, mock_boto_client):
        """Test detection when no stacks exist (first deployment)"""
        mock_cfn = MagicMock()
        mock_boto_client.return_value = mock_cfn
        
        # All stacks not found
        def describe_stacks_side_effect(StackName):
            error = ClientError(
                {'Error': {'Code': 'ValidationError', 'Message': 'Stack does not exist'}},
                'describe_stacks'
            )
            raise error
        
        mock_cfn.describe_stacks.side_effect = describe_stacks_side_effect
        
        result = self.service.detect_existing_stacks(
            capability_name='test-capability',
            environment='prod',
            region='us-west-2',
            deploy_frontend=True,
            deploy_backend=True
        )
        
        assert result.has_existing_stacks == False
        assert len(result.stacks_found) == 0
        assert result.recommended_strategy == DeploymentStrategy.UPDATE_EXISTING
        assert "first deployment" in result.recommendation_reason.lower() or "no existing stacks" in result.recommendation_reason.lower()
    
    @patch('app.services.stack_detection_service.boto3.client')
    def test_multi_region_detection(self, mock_boto_client):
        """Test detection across multiple regions (us-east-1 for global, target for regional)"""
        mock_cfn = MagicMock()
        mock_boto_client.return_value = mock_cfn
        
        # Track which regions were queried
        regions_queried = []
        
        def client_side_effect(service_name, region_name, **kwargs):
            regions_queried.append(region_name)
            return mock_cfn
        
        mock_boto_client.side_effect = client_side_effect
        
        def describe_stacks_side_effect(StackName):
            return {
                'Stacks': [{
                    'StackName': StackName,
                    'StackStatus': 'CREATE_COMPLETE',
                    'CreationTime': datetime.utcnow(),
                    'StackStatusReason': None
                }]
            }
        
        mock_cfn.describe_stacks.side_effect = describe_stacks_side_effect
        
        result = self.service.detect_existing_stacks(
            capability_name='test-capability',
            environment='prod',
            region='us-west-2',
            deploy_frontend=True,
            deploy_backend=True
        )
        
        # Verify us-east-1 was queried for frontend-global
        assert 'us-east-1' in regions_queried
        # Verify target region was queried for other stacks
        assert 'us-west-2' in regions_queried
    
    @patch('app.services.stack_detection_service.boto3.client')
    def test_error_handling_access_denied(self, mock_boto_client):
        """Test graceful handling of AccessDeniedException"""
        mock_cfn = MagicMock()
        mock_boto_client.return_value = mock_cfn
        
        def describe_stacks_side_effect(StackName):
            if 'frontend-global' in StackName:
                # Access denied for this stack
                error = ClientError(
                    {'Error': {'Code': 'AccessDeniedException', 'Message': 'Access denied'}},
                    'describe_stacks'
                )
                raise error
            else:
                # Other stacks succeed
                return {
                    'Stacks': [{
                        'StackName': StackName,
                        'StackStatus': 'CREATE_COMPLETE',
                        'CreationTime': datetime.utcnow(),
                        'StackStatusReason': None
                    }]
                }
        
        mock_cfn.describe_stacks.side_effect = describe_stacks_side_effect
        
        result = self.service.detect_existing_stacks(
            capability_name='test-capability',
            environment='prod',
            region='us-west-2',
            deploy_frontend=True,
            deploy_backend=True
        )
        
        # Should return partial results with error message
        assert result.error_message is not None
        assert "AccessDeniedException" in result.error_message or "Access denied" in result.error_message
        # Should still have results for stacks that succeeded
        assert len(result.stacks_found) > 0
    
    @patch('app.services.stack_detection_service.boto3.client')
    def test_error_handling_stack_not_found(self, mock_boto_client):
        """Test that stack not found is not treated as an error"""
        mock_cfn = MagicMock()
        mock_boto_client.return_value = mock_cfn
        
        def describe_stacks_side_effect(StackName):
            error = ClientError(
                {'Error': {'Code': 'ValidationError', 'Message': 'Stack does not exist'}},
                'describe_stacks'
            )
            raise error
        
        mock_cfn.describe_stacks.side_effect = describe_stacks_side_effect
        
        result = self.service.detect_existing_stacks(
            capability_name='test-capability',
            environment='prod',
            region='us-west-2',
            deploy_frontend=True,
            deploy_backend=True
        )
        
        # Should not have error message for stack not found
        assert result.error_message is None or result.error_message == ""
        assert result.has_existing_stacks == False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
