"""
Property-based tests for Resource Resolver.

Feature: template-bundling-validation, Property 2: Path Resolution Returns Correct Absolute Paths

For any template request in any runtime environment (Electron packaged, PyInstaller, development),
the Resource_Resolver SHALL return an absolute path that correctly points to the template location
for that environment.

Validates: Requirements 2.1, 2.2, 2.3
"""
import pytest
import tempfile
import shutil
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from hypothesis import given, strategies as st, settings, assume

from app.utils.resource_resolver import ResourceResolver, TemplateNotFoundError


# Strategies for generating test data
template_name_strategy = st.sampled_from([
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

relative_path_strategy = st.sampled_from([
    "backend/foundation-stack.yaml",
    "backend/iam-roles-stack.yaml",
    "backend/storage-stack.yaml",
    "frontend/global-stack.yaml",
    "frontend/cognito-stack.yaml",
])


class TestPathResolutionProperty:
    """
    **Feature: template-bundling-validation, Property 2: Path Resolution Returns Correct Absolute Paths**
    
    For any template request in any runtime environment (Electron packaged, PyInstaller, development),
    the Resource_Resolver SHALL return an absolute path that correctly points to the template location
    for that environment.
    
    **Validates: Requirements 2.1, 2.2, 2.3**
    """
    
    @given(template_name_strategy)
    @settings(max_examples=100)
    def test_resolved_paths_are_absolute(self, template_name):
        """
        Property: All resolved template paths must be absolute paths.
        """
        # Create a temporary templates directory with the required structure
        temp_dir = tempfile.mkdtemp()
        try:
            # Create template structure
            templates_dir = Path(temp_dir) / "deploy" / "templates"
            (templates_dir / "backend").mkdir(parents=True)
            (templates_dir / "frontend").mkdir(parents=True)
            
            # Create the template file
            relative_path = ResourceResolver.TEMPLATE_MAP[template_name]
            template_path = templates_dir / relative_path
            template_path.write_text("AWSTemplateFormatVersion: '2010-09-09'\nResources: {}")
            
            # Mock the get_templates_dir to return our temp directory
            with patch.object(ResourceResolver, 'get_templates_dir', return_value=templates_dir):
                resolved_path = ResourceResolver.get_template_path(template_name)
                
                # Property: Path must be absolute
                assert resolved_path.is_absolute(), \
                    f"Resolved path {resolved_path} should be absolute"
                
                # Property: Path must exist (since we created it)
                assert resolved_path.exists(), \
                    f"Resolved path {resolved_path} should exist"
                
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    @given(template_name_strategy)
    @settings(max_examples=100)
    def test_electron_mode_uses_resources_templates(self, template_name):
        """
        Property: In Electron packaged mode, templates are resolved from resources/templates/.
        """
        temp_dir = tempfile.mkdtemp()
        try:
            # Create Electron-style resource structure
            electron_resources = Path(temp_dir) / "resources"
            templates_dir = electron_resources / "templates"
            (templates_dir / "backend").mkdir(parents=True)
            (templates_dir / "frontend").mkdir(parents=True)
            
            # Create the template file
            relative_path = ResourceResolver.TEMPLATE_MAP[template_name]
            template_path = templates_dir / relative_path
            template_path.write_text("AWSTemplateFormatVersion: '2010-09-09'\nResources: {}")
            
            # Simulate Electron environment
            with patch.dict(os.environ, {'ELECTRON_RESOURCES_PATH': str(electron_resources)}):
                resolved_dir = ResourceResolver.get_templates_dir()
                
                # Property: Should use Electron resources path
                assert str(resolved_dir) == str(templates_dir), \
                    f"Should use Electron templates path, got {resolved_dir}"
                
                # Property: Environment detection should report Electron
                assert ResourceResolver.is_electron(), \
                    "Should detect Electron environment"
                assert ResourceResolver.is_packaged(), \
                    "Should detect packaged environment"
                
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    @given(template_name_strategy)
    @settings(max_examples=100)
    def test_pyinstaller_mode_uses_meipass(self, template_name):
        """
        Property: In PyInstaller mode, templates are resolved from _MEIPASS/deploy/templates/.
        """
        temp_dir = tempfile.mkdtemp()
        try:
            # Create PyInstaller-style structure
            meipass_dir = Path(temp_dir) / "_MEIPASS"
            templates_dir = meipass_dir / "deploy" / "templates"
            (templates_dir / "backend").mkdir(parents=True)
            (templates_dir / "frontend").mkdir(parents=True)
            
            # Create the template file
            relative_path = ResourceResolver.TEMPLATE_MAP[template_name]
            template_path = templates_dir / relative_path
            template_path.write_text("AWSTemplateFormatVersion: '2010-09-09'\nResources: {}")
            
            # Simulate PyInstaller environment (without Electron)
            with patch.dict(os.environ, {}, clear=False):
                # Remove ELECTRON_RESOURCES_PATH if present
                os.environ.pop('ELECTRON_RESOURCES_PATH', None)
                
                with patch.object(sys, 'frozen', True, create=True):
                    with patch.object(sys, '_MEIPASS', str(meipass_dir), create=True):
                        resolved_dir = ResourceResolver.get_templates_dir()
                        
                        # Property: Should use PyInstaller MEIPASS path
                        assert str(resolved_dir) == str(templates_dir), \
                            f"Should use PyInstaller templates path, got {resolved_dir}"
                        
                        # Property: Environment detection should report PyInstaller
                        assert ResourceResolver.is_pyinstaller(), \
                            "Should detect PyInstaller environment"
                        assert ResourceResolver.is_packaged(), \
                            "Should detect packaged environment"
                        
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    def test_development_mode_uses_relative_path(self):
        """
        Property: In development mode, templates are resolved from deploy/templates/ relative to project.
        """
        # Clear any packaged environment indicators
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('ELECTRON_RESOURCES_PATH', None)
            
            # Ensure not in PyInstaller mode
            if hasattr(sys, 'frozen'):
                delattr(sys, 'frozen')
            if hasattr(sys, '_MEIPASS'):
                delattr(sys, '_MEIPASS')
            
            # Property: Should not detect packaged environment
            assert not ResourceResolver.is_packaged(), \
                "Should not detect packaged environment in dev mode"
            assert not ResourceResolver.is_electron(), \
                "Should not detect Electron in dev mode"
            assert not ResourceResolver.is_pyinstaller(), \
                "Should not detect PyInstaller in dev mode"
            
            # Get templates dir - should be relative to project
            templates_dir = ResourceResolver.get_templates_dir()
            
            # Property: Path should be absolute
            assert templates_dir.is_absolute(), \
                f"Templates dir {templates_dir} should be absolute"
    
    @given(template_name_strategy)
    @settings(max_examples=50)
    def test_template_path_contains_correct_filename(self, template_name):
        """
        Property: Resolved path should contain the correct template filename.
        """
        temp_dir = tempfile.mkdtemp()
        try:
            # Create template structure
            templates_dir = Path(temp_dir) / "templates"
            (templates_dir / "backend").mkdir(parents=True)
            (templates_dir / "frontend").mkdir(parents=True)
            
            # Create the template file
            relative_path = ResourceResolver.TEMPLATE_MAP[template_name]
            template_path = templates_dir / relative_path
            template_path.write_text("AWSTemplateFormatVersion: '2010-09-09'\nResources: {}")
            
            expected_filename = Path(relative_path).name
            
            with patch.object(ResourceResolver, 'get_templates_dir', return_value=templates_dir):
                resolved_path = ResourceResolver.get_template_path(template_name)
                
                # Property: Filename should match expected
                assert resolved_path.name == expected_filename, \
                    f"Expected filename {expected_filename}, got {resolved_path.name}"
                
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestEnvironmentInfo:
    """
    Tests for environment information reporting.
    """
    
    def test_environment_info_contains_required_fields(self):
        """
        Property: Environment info should contain all required fields.
        """
        info = ResourceResolver.get_environment_info()
        
        required_fields = [
            'is_packaged',
            'is_electron',
            'is_pyinstaller',
            'environment_type',
            'cwd',
        ]
        
        for field in required_fields:
            assert field in info, f"Environment info should contain '{field}'"
    
    def test_environment_type_is_valid(self):
        """
        Property: Environment type should be one of the valid types.
        """
        info = ResourceResolver.get_environment_info()
        
        valid_types = ['development', 'electron_packaged', 'pyinstaller_bundle']
        assert info['environment_type'] in valid_types, \
            f"Environment type should be one of {valid_types}, got {info['environment_type']}"


class TestTemplateNotFoundError:
    """
    Tests for TemplateNotFoundError behavior.
    """
    
    @given(st.text(min_size=1, max_size=50))
    @settings(max_examples=50)
    def test_error_contains_template_name(self, template_name):
        """
        Property: Error message should contain the template name.
        """
        assume(template_name.strip())  # Skip empty/whitespace names
        
        searched_paths = ["/path/one", "/path/two"]
        error = TemplateNotFoundError(template_name, searched_paths)
        
        assert template_name in str(error), \
            f"Error message should contain template name '{template_name}'"
    
    @given(st.lists(st.text(min_size=1, max_size=100), min_size=1, max_size=5))
    @settings(max_examples=50)
    def test_error_contains_all_searched_paths(self, searched_paths):
        """
        Property: Error message should contain all searched paths.
        """
        # Filter out empty paths
        searched_paths = [p for p in searched_paths if p.strip()]
        assume(len(searched_paths) > 0)
        
        error = TemplateNotFoundError("test-template", searched_paths)
        error_str = str(error)
        
        for path in searched_paths:
            assert path in error_str, \
                f"Error message should contain searched path '{path}'"
    
    def test_error_contains_remediation(self):
        """
        Property: Error message should contain remediation advice.
        """
        error = TemplateNotFoundError("test-template", ["/some/path"])
        
        assert "Remediation:" in str(error), \
            "Error message should contain remediation section"
        assert error.remediation, \
            "Error should have remediation attribute"


class TestGetAllTemplatePaths:
    """
    Tests for get_all_template_paths functionality.
    """
    
    def test_returns_only_existing_templates(self):
        """
        Property: get_all_template_paths should only return paths to existing templates.
        """
        temp_dir = tempfile.mkdtemp()
        try:
            # Create template structure with only some templates
            templates_dir = Path(temp_dir) / "templates"
            (templates_dir / "backend").mkdir(parents=True)
            (templates_dir / "frontend").mkdir(parents=True)
            
            # Create only a subset of templates
            (templates_dir / "backend" / "foundation-stack.yaml").write_text("Resources: {}")
            (templates_dir / "frontend" / "global-stack.yaml").write_text("Resources: {}")
            
            with patch.object(ResourceResolver, 'get_templates_dir', return_value=templates_dir):
                all_paths = ResourceResolver.get_all_template_paths()
                
                # Property: All returned paths should exist
                for stack_type, path in all_paths.items():
                    assert path.exists(), \
                        f"Path for {stack_type} should exist: {path}"
                
                # Property: Should only include templates that exist
                assert "backend-foundation" in all_paths
                assert "frontend-global" in all_paths
                assert "backend-storage" not in all_paths  # We didn't create this one
                
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
