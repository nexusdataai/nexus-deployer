"""
Unit tests for stack state classification
Tests the _classify_stack_state method to ensure all CloudFormation statuses
are correctly classified as updatable, failed, or in_progress
"""
import pytest
from app.services.stack_detection_service import StackDetectionService


class TestStackClassification:
    """Test stack state classification logic"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.service = StackDetectionService()
    
    def test_create_complete_is_updatable(self):
        """Test CREATE_COMPLETE status is classified as updatable"""
        result = self.service._classify_stack_state('CREATE_COMPLETE')
        assert result == "updatable"
    
    def test_update_complete_is_updatable(self):
        """Test UPDATE_COMPLETE status is classified as updatable"""
        result = self.service._classify_stack_state('UPDATE_COMPLETE')
        assert result == "updatable"
    
    def test_rollback_complete_is_failed(self):
        """Test ROLLBACK_COMPLETE status is classified as failed"""
        result = self.service._classify_stack_state('ROLLBACK_COMPLETE')
        assert result == "failed"
    
    def test_update_rollback_complete_is_failed(self):
        """Test UPDATE_ROLLBACK_COMPLETE status is classified as failed"""
        result = self.service._classify_stack_state('UPDATE_ROLLBACK_COMPLETE')
        assert result == "failed"
    
    def test_delete_failed_is_failed(self):
        """Test DELETE_FAILED status is classified as failed"""
        result = self.service._classify_stack_state('DELETE_FAILED')
        assert result == "failed"
    
    def test_create_failed_is_failed(self):
        """Test CREATE_FAILED status is classified as failed"""
        result = self.service._classify_stack_state('CREATE_FAILED')
        assert result == "failed"
    
    def test_create_in_progress_is_in_progress(self):
        """Test CREATE_IN_PROGRESS status is classified as in_progress"""
        result = self.service._classify_stack_state('CREATE_IN_PROGRESS')
        assert result == "in_progress"
    
    def test_update_in_progress_is_in_progress(self):
        """Test UPDATE_IN_PROGRESS status is classified as in_progress"""
        result = self.service._classify_stack_state('UPDATE_IN_PROGRESS')
        assert result == "in_progress"
    
    def test_delete_in_progress_is_in_progress(self):
        """Test DELETE_IN_PROGRESS status is classified as in_progress"""
        result = self.service._classify_stack_state('DELETE_IN_PROGRESS')
        assert result == "in_progress"
    
    def test_rollback_in_progress_is_in_progress(self):
        """Test ROLLBACK_IN_PROGRESS status is classified as in_progress"""
        result = self.service._classify_stack_state('ROLLBACK_IN_PROGRESS')
        assert result == "in_progress"
    
    def test_update_rollback_in_progress_is_in_progress(self):
        """Test UPDATE_ROLLBACK_IN_PROGRESS status is classified as in_progress"""
        result = self.service._classify_stack_state('UPDATE_ROLLBACK_IN_PROGRESS')
        assert result == "in_progress"
    
    def test_unknown_status_defaults_to_updatable(self):
        """Test unknown status is treated as updatable with warning"""
        result = self.service._classify_stack_state('UNKNOWN_STATUS')
        assert result == "updatable"
    
    def test_all_updatable_states(self):
        """Test all updatable states are correctly classified"""
        updatable_states = ['CREATE_COMPLETE', 'UPDATE_COMPLETE']
        for status in updatable_states:
            result = self.service._classify_stack_state(status)
            assert result == "updatable", f"{status} should be updatable"
    
    def test_all_failed_states(self):
        """Test all failed states are correctly classified"""
        failed_states = [
            'ROLLBACK_COMPLETE',
            'UPDATE_ROLLBACK_COMPLETE',
            'DELETE_FAILED',
            'CREATE_FAILED'
        ]
        for status in failed_states:
            result = self.service._classify_stack_state(status)
            assert result == "failed", f"{status} should be failed"
    
    def test_all_in_progress_states(self):
        """Test all in-progress states are correctly classified"""
        in_progress_states = [
            'CREATE_IN_PROGRESS',
            'UPDATE_IN_PROGRESS',
            'DELETE_IN_PROGRESS',
            'ROLLBACK_IN_PROGRESS',
            'UPDATE_ROLLBACK_IN_PROGRESS'
        ]
        for status in in_progress_states:
            result = self.service._classify_stack_state(status)
            assert result == "in_progress", f"{status} should be in_progress"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
