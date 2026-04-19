"""
Unit tests for decision tree logic
Tests the _recommend_strategy method to ensure correct strategy recommendations
based on stack states
"""
import pytest
from datetime import datetime
from app.services.stack_detection_service import StackDetectionService
from app.models.stack_detection import ExistingStackInfo, DeploymentStrategy


class TestDecisionTreeLogic:
    """Test decision tree recommendation logic"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.service = StackDetectionService()
    
    def test_no_stacks_recommends_update_existing(self):
        """Test that no stacks results in UPDATE_EXISTING recommendation"""
        stacks = []
        strategy, reason = self.service._recommend_strategy(stacks)
        
        assert strategy == DeploymentStrategy.UPDATE_EXISTING
        assert "first deployment" in reason.lower() or "no existing stacks" in reason.lower()
    
    def test_all_updatable_stacks_recommends_update_existing(self):
        """Test that all updatable stacks results in UPDATE_EXISTING recommendation"""
        stacks = [
            ExistingStackInfo(
                stack_name="test-prod-frontend-global",
                stack_type="frontend-global",
                stack_status="CREATE_COMPLETE",
                region="us-east-1",
                is_updatable=True,
                classification="updatable"
            ),
            ExistingStackInfo(
                stack_name="test-prod-backend-service",
                stack_type="backend-service",
                stack_status="UPDATE_COMPLETE",
                region="us-west-2",
                is_updatable=True,
                classification="updatable"
            )
        ]
        
        strategy, reason = self.service._recommend_strategy(stacks)
        
        assert strategy == DeploymentStrategy.UPDATE_EXISTING
        assert "stable" in reason.lower() or "updatable" in reason.lower()
    
    def test_failed_stack_recommends_clean_deploy(self):
        """Test that any failed stack results in CLEAN_DEPLOY recommendation"""
        stacks = [
            ExistingStackInfo(
                stack_name="test-prod-frontend-global",
                stack_type="frontend-global",
                stack_status="CREATE_COMPLETE",
                region="us-east-1",
                is_updatable=True,
                classification="updatable"
            ),
            ExistingStackInfo(
                stack_name="test-prod-backend-service",
                stack_type="backend-service",
                stack_status="ROLLBACK_COMPLETE",
                region="us-west-2",
                is_updatable=False,
                classification="failed"
            )
        ]
        
        strategy, reason = self.service._recommend_strategy(stacks)
        
        assert strategy == DeploymentStrategy.CLEAN_DEPLOY
        assert "failed" in reason.lower()
        assert "test-prod-backend-service" in reason
        assert "ROLLBACK_COMPLETE" in reason
    
    def test_in_progress_stack_recommends_wait(self):
        """Test that any in-progress stack results in None (wait) recommendation"""
        stacks = [
            ExistingStackInfo(
                stack_name="test-prod-frontend-global",
                stack_type="frontend-global",
                stack_status="UPDATE_IN_PROGRESS",
                region="us-east-1",
                is_updatable=False,
                classification="in_progress"
            )
        ]
        
        strategy, reason = self.service._recommend_strategy(stacks)
        
        assert strategy is None
        assert "wait" in reason.lower() or "in-progress" in reason.lower()
        assert "test-prod-frontend-global" in reason
    
    def test_mixed_updatable_and_not_found_recommends_update_existing(self):
        """Test that mix of updatable and not-found stacks recommends UPDATE_EXISTING"""
        stacks = [
            ExistingStackInfo(
                stack_name="test-prod-frontend-global",
                stack_type="frontend-global",
                stack_status="CREATE_COMPLETE",
                region="us-east-1",
                is_updatable=True,
                classification="updatable"
            )
            # Some stacks not found (not in list) - should still recommend UPDATE_EXISTING
        ]
        
        strategy, reason = self.service._recommend_strategy(stacks)
        
        assert strategy == DeploymentStrategy.UPDATE_EXISTING
    
    def test_multiple_failed_stacks_lists_all_in_reason(self):
        """Test that multiple failed stacks are all listed in the reason"""
        stacks = [
            ExistingStackInfo(
                stack_name="test-prod-frontend-global",
                stack_type="frontend-global",
                stack_status="ROLLBACK_COMPLETE",
                region="us-east-1",
                is_updatable=False,
                classification="failed"
            ),
            ExistingStackInfo(
                stack_name="test-prod-backend-service",
                stack_type="backend-service",
                stack_status="UPDATE_ROLLBACK_COMPLETE",
                region="us-west-2",
                is_updatable=False,
                classification="failed"
            )
        ]
        
        strategy, reason = self.service._recommend_strategy(stacks)
        
        assert strategy == DeploymentStrategy.CLEAN_DEPLOY
        assert "test-prod-frontend-global" in reason
        assert "test-prod-backend-service" in reason
        assert "ROLLBACK_COMPLETE" in reason
        assert "UPDATE_ROLLBACK_COMPLETE" in reason
    
    def test_multiple_in_progress_stacks_lists_all_in_reason(self):
        """Test that multiple in-progress stacks are all listed in the reason"""
        stacks = [
            ExistingStackInfo(
                stack_name="test-prod-frontend-global",
                stack_type="frontend-global",
                stack_status="CREATE_IN_PROGRESS",
                region="us-east-1",
                is_updatable=False,
                classification="in_progress"
            ),
            ExistingStackInfo(
                stack_name="test-prod-backend-service",
                stack_type="backend-service",
                stack_status="UPDATE_IN_PROGRESS",
                region="us-west-2",
                is_updatable=False,
                classification="in_progress"
            )
        ]
        
        strategy, reason = self.service._recommend_strategy(stacks)
        
        assert strategy is None
        assert "test-prod-frontend-global" in reason
        assert "test-prod-backend-service" in reason
    
    def test_in_progress_takes_precedence_over_failed(self):
        """Test that in-progress stacks are checked before failed stacks"""
        stacks = [
            ExistingStackInfo(
                stack_name="test-prod-frontend-global",
                stack_type="frontend-global",
                stack_status="UPDATE_IN_PROGRESS",
                region="us-east-1",
                is_updatable=False,
                classification="in_progress"
            ),
            ExistingStackInfo(
                stack_name="test-prod-backend-service",
                stack_type="backend-service",
                stack_status="ROLLBACK_COMPLETE",
                region="us-west-2",
                is_updatable=False,
                classification="failed"
            )
        ]
        
        strategy, reason = self.service._recommend_strategy(stacks)
        
        # Should recommend waiting for in-progress, not clean deploy for failed
        assert strategy is None
        assert "wait" in reason.lower() or "in-progress" in reason.lower()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
