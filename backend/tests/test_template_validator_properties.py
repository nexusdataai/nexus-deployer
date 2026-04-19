"""
Property-based tests for Template Validator.

Feature: template-bundling-validation

Tests cover:
- Property 3: Template Validation Checks All Required Templates
- Property 4: Missing Template Errors Include All Missing Files
- Property 5: Template Integrity Validation Checks YAML and CloudFormation Structure

Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2
"""
import pytest
import tempfile
import shutil
import os
from pathlib import Path
from unittest.mock import patch
from hypothesis import given, strategies as st, settings, assume

from app.services.template_validator import (
    TemplateValidator,
    TemplateValidationResult,
    MissingTemplate,
    IntegrityIssue
)
from app.utils.resource_resolver import ResourceResolver


# Strategies for generating test data
stack_type_strategy = st.sampled_from([
    "backend-foundation",
    "backend-iam-roles",
    "backend-regional-cert",
    "backend-storage",
    "backend-network",
    "backend-service",
    "backend-domain",
    "frontend-global",
    "frontend-cognito",
    "frontend-regional",
])

# Strategy for generating valid CloudFormation YAML content
valid_cfn_content_strategy = st.sampled_from([
    "AWSTemplateFormatVersion: '2010-09-09'\nResources:\n  DummyResource:\n    Type: AWS::CloudFormation::WaitConditionHandle",
    "Resources:\n  MyBucket:\n    Type: AWS::S3::Bucket",
    "AWSTemplateFormatVersion: '2010-09-09'\nDescription: Test template\nResources: {}",
])

# Strategy for generating invalid YAML content
invalid_yaml_strategy = st.sampled_from([
    "invalid: yaml: content:",
    "  - broken\n- indentation",
    "key: [unclosed bracket",
    "{{not yaml}}",
])

# Strategy for generating YAML that's valid but not CloudFormation
non_cfn_yaml_strategy = st.sampled_from([
    "name: test\nversion: 1.0",
    "items:\n  - one\n  - two",
    "config:\n  setting: value",
])


def create_template_structure(temp_dir: Path, templates: dict) -> Path:
    """
    Create a template directory structure for testing.
    
    Args:
        temp_dir: Base temporary directory
        templates: Dict mapping relative paths to content (or None for missing)
        
    Returns:
        Path to the templates directory
    """
    templates_dir = temp_dir / "templates"
    (templates_dir / "backend").mkdir(parents=True)
    (templates_dir / "frontend").mkdir(parents=True)
    
    for rel_path, content in templates.items():
        if content is not None:
            file_path = templates_dir / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)
    
    return templates_dir


class TestTemplateValidationProperty:
    """
    **Feature: template-bundling-validation, Property 3: Template Validation Checks All Required Templates**
    
    For any deployment configuration specifying a capability, the Template_Validator SHALL check
    the existence of all templates referenced by that capability before allowing deployment to proceed.
    
    **Validates: Requirements 3.1, 3.2, 3.4**
    """
    
    @given(st.booleans(), st.booleans())
    @settings(max_examples=100)
    def test_validates_all_required_templates(self, deploy_frontend, deploy_backend):
        """
        Property: All required templates for the deployment configuration are checked.
        """
        # Skip if neither frontend nor backend is being deployed
        assume(deploy_frontend or deploy_backend)
        
        temp_dir = Path(tempfile.mkdtemp())
        try:
            # Create all templates
            all_templates = {}
            valid_content = "AWSTemplateFormatVersion: '2010-09-09'\nResources: {}"
            
            for stack_type, rel_path in ResourceResolver.TEMPLATE_MAP.items():
                all_templates[rel_path] = valid_content
            
            templates_dir = create_template_structure(temp_dir, all_templates)
            
            with patch.object(ResourceResolver, 'get_templates_dir', return_value=templates_dir):
                validator = TemplateValidator()
                result = validator.validate_templates(
                    deploy_frontend=deploy_frontend,
                    deploy_backend=deploy_backend,
                    check_integrity=False
                )
                
                # Property: All required templates should be checked
                expected_templates = []
                if deploy_backend:
                    expected_templates.extend(validator.BACKEND_STACK_TYPES)
                if deploy_frontend:
                    expected_templates.extend(validator.FRONTEND_STACK_TYPES)
                
                assert set(result.templates_checked) == set(expected_templates), \
                    f"Should check all required templates. Expected {expected_templates}, got {result.templates_checked}"
                
                # Property: With all templates present, validation should succeed
                assert result.success, \
                    f"Validation should succeed when all templates exist. Issues: {result.missing_templates}"
                
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    @given(st.lists(stack_type_strategy, min_size=1, max_size=5, unique=True))
    @settings(max_examples=100)
    def test_detects_missing_templates(self, missing_stack_types):
        """
        Property: Missing templates are detected and reported.
        """
        temp_dir = Path(tempfile.mkdtemp())
        try:
            # Create templates, but skip the ones we want to be missing
            all_templates = {}
            valid_content = "AWSTemplateFormatVersion: '2010-09-09'\nResources: {}"
            
            for stack_type, rel_path in ResourceResolver.TEMPLATE_MAP.items():
                if stack_type not in missing_stack_types:
                    all_templates[rel_path] = valid_content
            
            templates_dir = create_template_structure(temp_dir, all_templates)
            
            with patch.object(ResourceResolver, 'get_templates_dir', return_value=templates_dir):
                validator = TemplateValidator()
                result = validator.validate_templates(
                    deploy_frontend=True,
                    deploy_backend=True,
                    check_integrity=False
                )
                
                # Property: All missing templates should be reported
                missing_names = [m.template_name for m in result.missing_templates]
                for stack_type in missing_stack_types:
                    assert stack_type in missing_names, \
                        f"Missing template {stack_type} should be reported"
                
                # Property: Validation should fail when templates are missing
                assert not result.success, \
                    "Validation should fail when templates are missing"
                
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestMissingTemplateErrorAggregation:
    """
    **Feature: template-bundling-validation, Property 4: Missing Template Errors Include All Missing Files**
    
    For any deployment where multiple templates are missing, the validation error SHALL report
    all missing templates in a single message, not just the first one found.
    
    **Validates: Requirements 3.3, 3.5**
    """
    
    @given(st.lists(stack_type_strategy, min_size=2, max_size=7, unique=True))
    @settings(max_examples=100)
    def test_reports_all_missing_templates(self, missing_stack_types):
        """
        Property: All missing templates are reported in a single validation result.
        """
        temp_dir = Path(tempfile.mkdtemp())
        try:
            # Create only templates that are NOT in missing_stack_types
            all_templates = {}
            valid_content = "AWSTemplateFormatVersion: '2010-09-09'\nResources: {}"
            
            for stack_type, rel_path in ResourceResolver.TEMPLATE_MAP.items():
                if stack_type not in missing_stack_types:
                    all_templates[rel_path] = valid_content
            
            templates_dir = create_template_structure(temp_dir, all_templates)
            
            with patch.object(ResourceResolver, 'get_templates_dir', return_value=templates_dir):
                validator = TemplateValidator()
                result = validator.validate_templates(
                    deploy_frontend=True,
                    deploy_backend=True,
                    check_integrity=False
                )
                
                # Property: Number of missing templates should match
                assert len(result.missing_templates) == len(missing_stack_types), \
                    f"Should report all {len(missing_stack_types)} missing templates, got {len(result.missing_templates)}"
                
                # Property: Each missing template should have expected_path and remediation
                for missing in result.missing_templates:
                    assert missing.expected_path, \
                        f"Missing template {missing.template_name} should have expected_path"
                    assert missing.remediation, \
                        f"Missing template {missing.template_name} should have remediation advice"
                
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    def test_summary_includes_missing_count(self):
        """
        Property: Summary should include count of missing templates.
        """
        temp_dir = Path(tempfile.mkdtemp())
        try:
            # Create empty templates directory (all templates missing)
            templates_dir = create_template_structure(temp_dir, {})
            
            with patch.object(ResourceResolver, 'get_templates_dir', return_value=templates_dir):
                validator = TemplateValidator()
                result = validator.validate_templates(
                    deploy_frontend=True,
                    deploy_backend=True,
                    check_integrity=False
                )
                
                # Property: Summary should mention missing templates
                assert "missing" in result.summary.lower(), \
                    f"Summary should mention missing templates: {result.summary}"
                
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestTemplateIntegrityValidation:
    """
    **Feature: template-bundling-validation, Property 5: Template Integrity Validation Checks YAML and CloudFormation Structure**
    
    For any template file, integrity validation SHALL verify it is valid YAML and contains
    either `AWSTemplateFormatVersion` or `Resources` section.
    
    **Validates: Requirements 4.1, 4.2**
    """
    
    @given(valid_cfn_content_strategy)
    @settings(max_examples=100)
    def test_valid_templates_pass_integrity_check(self, content):
        """
        Property: Valid CloudFormation templates pass integrity validation.
        """
        temp_dir = Path(tempfile.mkdtemp())
        try:
            template_path = temp_dir / "test-template.yaml"
            template_path.write_text(content)
            
            validator = TemplateValidator()
            result = validator.validate_template_integrity(template_path)
            
            # Property: Valid templates should not have integrity issues
            assert result is None, \
                f"Valid template should pass integrity check, got: {result}"
                
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    @given(invalid_yaml_strategy)
    @settings(max_examples=100)
    def test_invalid_yaml_detected(self, content):
        """
        Property: Invalid YAML is detected and reported.
        """
        temp_dir = Path(tempfile.mkdtemp())
        try:
            template_path = temp_dir / "test-template.yaml"
            template_path.write_text(content)
            
            validator = TemplateValidator()
            result = validator.validate_template_integrity(template_path)
            
            # Property: Invalid YAML should be detected
            assert result is not None, \
                "Invalid YAML should be detected"
            assert result.issue_type == "invalid_yaml", \
                f"Issue type should be 'invalid_yaml', got '{result.issue_type}'"
            assert "yaml" in result.details.lower() or "parsing" in result.details.lower(), \
                f"Details should mention YAML error: {result.details}"
                
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    @given(non_cfn_yaml_strategy)
    @settings(max_examples=100)
    def test_missing_cfn_sections_detected(self, content):
        """
        Property: YAML without CloudFormation sections is detected.
        """
        temp_dir = Path(tempfile.mkdtemp())
        try:
            template_path = temp_dir / "test-template.yaml"
            template_path.write_text(content)
            
            validator = TemplateValidator()
            result = validator.validate_template_integrity(template_path)
            
            # Property: Missing CFN sections should be detected
            assert result is not None, \
                "Missing CloudFormation sections should be detected"
            assert result.issue_type == "missing_cfn_section", \
                f"Issue type should be 'missing_cfn_section', got '{result.issue_type}'"
            assert "AWSTemplateFormatVersion" in result.details or "Resources" in result.details, \
                f"Details should mention required sections: {result.details}"
                
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    def test_empty_file_detected(self):
        """
        Property: Empty template files are detected.
        """
        temp_dir = Path(tempfile.mkdtemp())
        try:
            template_path = temp_dir / "test-template.yaml"
            template_path.write_text("")
            
            validator = TemplateValidator()
            result = validator.validate_template_integrity(template_path)
            
            # Property: Empty files should be detected
            assert result is not None, \
                "Empty template should be detected"
            assert "empty" in result.details.lower(), \
                f"Details should mention empty file: {result.details}"
                
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    def test_integrity_issues_aggregated_with_missing(self):
        """
        Property: Integrity issues are reported alongside missing templates.
        """
        temp_dir = Path(tempfile.mkdtemp())
        try:
            # Create some valid templates, some invalid, and leave some missing
            templates = {
                "backend/foundation-stack.yaml": "AWSTemplateFormatVersion: '2010-09-09'\nResources: {}",
                "backend/iam-roles-stack.yaml": "invalid: yaml: content:",  # Invalid YAML
                "backend/storage-stack.yaml": "name: not-cfn",  # Valid YAML but not CFN
                # backend/network-stack.yaml is missing
            }
            
            templates_dir = create_template_structure(temp_dir, templates)
            
            with patch.object(ResourceResolver, 'get_templates_dir', return_value=templates_dir):
                validator = TemplateValidator()
                result = validator.validate_templates(
                    deploy_frontend=False,
                    deploy_backend=True,
                    check_integrity=True
                )
                
                # Property: Both missing and integrity issues should be reported
                assert len(result.missing_templates) > 0, \
                    "Should report missing templates"
                assert len(result.integrity_issues) > 0, \
                    "Should report integrity issues"
                
                # Property: Validation should fail
                assert not result.success, \
                    "Validation should fail with missing and invalid templates"
                
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestValidationResultSerialization:
    """
    Tests for validation result serialization.
    """
    
    def test_result_to_dict(self):
        """
        Property: Validation results can be serialized to dict.
        """
        result = TemplateValidationResult(
            success=False,
            templates_checked=["backend-foundation", "backend-storage"],
            missing_templates=[
                MissingTemplate(
                    template_name="backend-storage",
                    expected_path="/path/to/template",
                    remediation="Reinstall the application"
                )
            ],
            integrity_issues=[
                IntegrityIssue(
                    template_path="/path/to/bad.yaml",
                    issue_type="invalid_yaml",
                    details="Parse error"
                )
            ],
            summary="Test summary"
        )
        
        result_dict = result.to_dict()
        
        # Property: All fields should be present
        assert 'success' in result_dict
        assert 'templates_checked' in result_dict
        assert 'missing_templates' in result_dict
        assert 'integrity_issues' in result_dict
        assert 'summary' in result_dict
        
        # Property: Values should match
        assert result_dict['success'] == False
        assert len(result_dict['missing_templates']) == 1
        assert len(result_dict['integrity_issues']) == 1
