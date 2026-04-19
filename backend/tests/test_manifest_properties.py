"""
Property-based tests for Template Manifest Generator.

Feature: template-bundling-validation

Tests cover:
- Property 6: Manifest Contains Required Fields for All Templates
- Property 7: Manifest Validation Detects Missing Templates

Validates: Requirements 5.1, 5.2, 5.3, 5.4
"""
import pytest
import tempfile
import shutil
import json
import hashlib
from pathlib import Path
from hypothesis import given, strategies as st, settings, assume

# Import the manifest generator functions
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from generate_template_manifest import (
    generate_manifest,
    find_templates,
    compute_file_hash,
    validate_manifest
)

from app.services.template_validator import TemplateValidator


# Strategies for generating test data
yaml_content_strategy = st.sampled_from([
    "AWSTemplateFormatVersion: '2010-09-09'\nResources: {}",
    "Resources:\n  MyBucket:\n    Type: AWS::S3::Bucket",
    "AWSTemplateFormatVersion: '2010-09-09'\nDescription: Test\nResources:\n  Dummy:\n    Type: AWS::CloudFormation::WaitConditionHandle",
])

filename_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_",
    min_size=3,
    max_size=20
).map(lambda s: f"{s}.yaml")


def create_test_templates(temp_dir: Path, template_specs: dict) -> Path:
    """
    Create test templates in a temporary directory.
    
    Args:
        temp_dir: Base temporary directory
        template_specs: Dict mapping relative paths to content
        
    Returns:
        Path to templates directory
    """
    templates_dir = temp_dir / "templates"
    templates_dir.mkdir(parents=True)
    
    for rel_path, content in template_specs.items():
        file_path = templates_dir / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
    
    return templates_dir


class TestManifestRequiredFields:
    """
    **Feature: template-bundling-validation, Property 6: Manifest Contains Required Fields for All Templates**
    
    For any generated template manifest, each template entry SHALL include
    relative_path, filename, and size_bytes fields.
    
    **Validates: Requirements 5.1, 5.2**
    """
    
    @given(st.lists(
        st.tuples(
            st.sampled_from(["backend", "frontend"]),
            filename_strategy,
            yaml_content_strategy
        ),
        min_size=1,
        max_size=5
    ))
    @settings(max_examples=100)
    def test_manifest_entries_have_required_fields(self, template_specs):
        """
        Property: Each manifest entry contains relative_path, filename, and size_bytes.
        """
        temp_dir = Path(tempfile.mkdtemp())
        try:
            # Create templates from specs
            templates = {}
            for subdir, filename, content in template_specs:
                rel_path = f"{subdir}/{filename}"
                templates[rel_path] = content
            
            templates_dir = create_test_templates(temp_dir, templates)
            output_path = temp_dir / "manifest.json"
            
            # Generate manifest
            manifest = generate_manifest(templates_dir, output_path)
            
            # Property: Each entry must have required fields
            for entry in manifest["templates"]:
                assert "relative_path" in entry, \
                    "Entry must have relative_path"
                assert "filename" in entry, \
                    "Entry must have filename"
                assert "size_bytes" in entry, \
                    "Entry must have size_bytes"
                
                # Property: Fields must have correct types
                assert isinstance(entry["relative_path"], str), \
                    "relative_path must be a string"
                assert isinstance(entry["filename"], str), \
                    "filename must be a string"
                assert isinstance(entry["size_bytes"], int), \
                    "size_bytes must be an integer"
                assert entry["size_bytes"] >= 0, \
                    "size_bytes must be non-negative"
                
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    @given(yaml_content_strategy)
    @settings(max_examples=100)
    def test_manifest_size_matches_actual_file_size(self, content):
        """
        Property: size_bytes in manifest matches actual file size.
        """
        temp_dir = Path(tempfile.mkdtemp())
        try:
            templates_dir = create_test_templates(temp_dir, {
                "backend/test-stack.yaml": content
            })
            output_path = temp_dir / "manifest.json"
            
            # Generate manifest
            manifest = generate_manifest(templates_dir, output_path)
            
            # Get actual file size
            actual_path = templates_dir / "backend" / "test-stack.yaml"
            actual_size = actual_path.stat().st_size
            
            # Property: Manifest size should match actual size
            entry = manifest["templates"][0]
            assert entry["size_bytes"] == actual_size, \
                f"Manifest size {entry['size_bytes']} should match actual size {actual_size}"
                
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    @given(yaml_content_strategy)
    @settings(max_examples=100)
    def test_manifest_hash_matches_actual_hash(self, content):
        """
        Property: sha256 in manifest matches actual file hash.
        """
        temp_dir = Path(tempfile.mkdtemp())
        try:
            templates_dir = create_test_templates(temp_dir, {
                "backend/test-stack.yaml": content
            })
            output_path = temp_dir / "manifest.json"
            
            # Generate manifest
            manifest = generate_manifest(templates_dir, output_path)
            
            # Compute actual hash
            actual_path = templates_dir / "backend" / "test-stack.yaml"
            actual_hash = compute_file_hash(actual_path)
            
            # Property: Manifest hash should match actual hash
            entry = manifest["templates"][0]
            assert entry["sha256"] == actual_hash, \
                f"Manifest hash should match actual hash"
                
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    def test_manifest_has_metadata(self):
        """
        Property: Manifest includes generation metadata.
        """
        temp_dir = Path(tempfile.mkdtemp())
        try:
            templates_dir = create_test_templates(temp_dir, {
                "backend/test-stack.yaml": "Resources: {}"
            })
            output_path = temp_dir / "manifest.json"
            
            # Generate manifest
            manifest = generate_manifest(templates_dir, output_path)
            
            # Property: Manifest should have metadata
            assert "generated_at" in manifest, \
                "Manifest should have generated_at timestamp"
            assert "template_count" in manifest, \
                "Manifest should have template_count"
            assert manifest["template_count"] == len(manifest["templates"]), \
                "template_count should match number of templates"
                
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestManifestValidationDetectsMissing:
    """
    **Feature: template-bundling-validation, Property 7: Manifest Validation Detects Missing Templates**
    
    For any application startup where templates are missing compared to the manifest,
    the Template_Validator SHALL warn about potentially incomplete installation.
    
    **Validates: Requirements 5.3, 5.4**
    """
    
    @given(st.lists(filename_strategy, min_size=2, max_size=5, unique=True))
    @settings(max_examples=100)
    def test_detects_missing_templates(self, filenames):
        """
        Property: Missing templates are detected when comparing against manifest.
        """
        temp_dir = Path(tempfile.mkdtemp())
        try:
            # Create all templates first
            templates = {f"backend/{fn}": "Resources: {}" for fn in filenames}
            templates_dir = create_test_templates(temp_dir, templates)
            output_path = templates_dir / "template-manifest.json"
            
            # Generate manifest with all templates
            generate_manifest(templates_dir, output_path)
            
            # Delete one template
            deleted_file = templates_dir / "backend" / filenames[0]
            deleted_file.unlink()
            
            # Validate - should detect missing template
            is_valid = validate_manifest(output_path, templates_dir)
            
            # Property: Validation should fail when templates are missing
            assert not is_valid, \
                "Validation should fail when templates are missing"
                
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    def test_detects_hash_mismatch(self):
        """
        Property: Modified templates are detected via hash mismatch.
        """
        temp_dir = Path(tempfile.mkdtemp())
        try:
            templates_dir = create_test_templates(temp_dir, {
                "backend/test-stack.yaml": "Resources: {}"
            })
            output_path = templates_dir / "template-manifest.json"
            
            # Generate manifest
            generate_manifest(templates_dir, output_path)
            
            # Modify the template
            template_path = templates_dir / "backend" / "test-stack.yaml"
            template_path.write_text("Resources:\n  Modified: true")
            
            # Validate - should detect hash mismatch
            is_valid = validate_manifest(output_path, templates_dir)
            
            # Property: Validation should fail when content changes
            assert not is_valid, \
                "Validation should fail when template content changes"
                
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    def test_valid_manifest_passes(self):
        """
        Property: Valid manifest with matching templates passes validation.
        """
        temp_dir = Path(tempfile.mkdtemp())
        try:
            templates_dir = create_test_templates(temp_dir, {
                "backend/test-stack.yaml": "Resources: {}",
                "frontend/ui-stack.yaml": "AWSTemplateFormatVersion: '2010-09-09'\nResources: {}"
            })
            output_path = templates_dir / "template-manifest.json"
            
            # Generate manifest
            generate_manifest(templates_dir, output_path)
            
            # Validate - should pass
            is_valid = validate_manifest(output_path, templates_dir)
            
            # Property: Validation should pass when all templates match
            assert is_valid, \
                "Validation should pass when all templates match manifest"
                
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestTemplateValidatorManifestIntegration:
    """
    Tests for TemplateValidator's manifest validation integration.
    """
    
    def test_validator_warns_on_missing_manifest(self):
        """
        Property: Validator warns when manifest is not found.
        """
        temp_dir = Path(tempfile.mkdtemp())
        try:
            templates_dir = create_test_templates(temp_dir, {
                "backend/test-stack.yaml": "Resources: {}"
            })
            
            # Don't create manifest
            from unittest.mock import patch
            from app.utils.resource_resolver import ResourceResolver
            
            with patch.object(ResourceResolver, 'get_templates_dir', return_value=templates_dir):
                with patch.object(ResourceResolver, 'get_manifest_path', return_value=templates_dir / "template-manifest.json"):
                    validator = TemplateValidator()
                    result = validator.validate_against_manifest()
                    
                    # Property: Should warn about missing manifest
                    assert not result.manifest_found, \
                        "Should report manifest not found"
                    assert len(result.warnings) > 0, \
                        "Should have warnings about missing manifest"
                    
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    def test_validator_reports_missing_templates_from_manifest(self):
        """
        Property: Validator reports templates missing compared to manifest.
        """
        temp_dir = Path(tempfile.mkdtemp())
        try:
            # Create templates and manifest
            templates_dir = create_test_templates(temp_dir, {
                "backend/test-stack.yaml": "Resources: {}",
                "backend/other-stack.yaml": "Resources: {}"
            })
            output_path = templates_dir / "template-manifest.json"
            generate_manifest(templates_dir, output_path)
            
            # Delete one template
            (templates_dir / "backend" / "other-stack.yaml").unlink()
            
            from unittest.mock import patch
            from app.utils.resource_resolver import ResourceResolver
            
            with patch.object(ResourceResolver, 'get_templates_dir', return_value=templates_dir):
                with patch.object(ResourceResolver, 'get_manifest_path', return_value=output_path):
                    validator = TemplateValidator()
                    result = validator.validate_against_manifest()
                    
                    # Property: Should report missing templates
                    assert len(result.missing_templates) > 0, \
                        "Should report missing templates"
                    assert "backend/other-stack.yaml" in result.missing_templates, \
                        "Should report the specific missing template"
                    assert not result.success, \
                        "Validation should fail with missing templates"
                    
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
