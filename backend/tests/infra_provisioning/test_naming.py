"""
Property tests for naming convention consistency.

Validates that all resource names follow the established naming convention:
- AWS resources: call-processing-{env}-{resource-name}
- SSM parameters: /call-processing/{env}/{category}/{name}
- Secrets: call-processing/{env}/{name}
- CloudWatch: /aws/call-processing/{env}
"""

import re
import pytest
from hypothesis import given, strategies as st, settings

from app.services.infra_provisioning.naming import ResourceNaming
from app.services.infra_provisioning.models import VALID_ENVIRONMENTS


# Strategies for property tests
env_strategy = st.sampled_from(list(VALID_ENVIRONMENTS))
ssm_category_strategy = st.sampled_from([
    "aws", "server", "cognito", "wxcc", "s3", "dynamodb", "glue", "cloudwatch"
])
ssm_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd'), whitelist_characters='-_'),
    min_size=1,
    max_size=50,
).filter(lambda x: x and not x.startswith('-') and not x.startswith('_'))


class TestNamingConventionConsistency:
    """Property tests for naming convention consistency (Requirement 8.3)."""
    
    @given(env=env_strategy)
    @settings(max_examples=20)
    def test_dynamodb_table_names_follow_convention(self, env: str):
        """
        Property 10.1: All DynamoDB table names follow the pattern
        call-processing-{env}-{resource-name}
        """
        naming = ResourceNaming(env)
        pattern = re.compile(rf"^call-processing-{env}-[a-z0-9-]+$")
        
        for table_name in naming.all_dynamodb_tables():
            assert pattern.match(table_name), (
                f"Table name '{table_name}' does not match pattern for env '{env}'"
            )
    
    @given(env=env_strategy)
    @settings(max_examples=20)
    def test_s3_bucket_names_follow_convention(self, env: str):
        """
        Property 10.2: All S3 bucket names follow the pattern
        call-processing-{env}-{resource-name}
        """
        naming = ResourceNaming(env)
        # S3 bucket names must be lowercase, 3-63 chars, no underscores
        pattern = re.compile(rf"^call-processing-{env}-[a-z0-9-]+$")
        
        for bucket_name in naming.all_s3_buckets():
            assert pattern.match(bucket_name), (
                f"Bucket name '{bucket_name}' does not match pattern for env '{env}'"
            )
            # S3 bucket name constraints
            assert len(bucket_name) >= 3, f"Bucket name too short: {bucket_name}"
            assert len(bucket_name) <= 63, f"Bucket name too long: {bucket_name}"
            assert "_" not in bucket_name, f"Bucket name contains underscore: {bucket_name}"
    
    @given(env=env_strategy, category=ssm_category_strategy, name=ssm_name_strategy)
    @settings(max_examples=50)
    def test_ssm_parameter_paths_follow_convention(self, env: str, category: str, name: str):
        """
        Property 10.3: All SSM parameter paths follow the pattern
        /call-processing/{env}/{category}/{name}
        """
        naming = ResourceNaming(env)
        param_path = naming.ssm_parameter(category, name)
        
        # Verify path structure
        assert param_path.startswith("/call-processing/"), (
            f"Parameter path must start with /call-processing/: {param_path}"
        )
        
        parts = param_path.split("/")
        assert len(parts) == 5, f"Parameter path should have 5 parts: {param_path}"
        assert parts[0] == "", "Path should start with /"
        assert parts[1] == "call-processing", f"Second part should be 'call-processing': {parts[1]}"
        assert parts[2] == env, f"Third part should be environment '{env}': {parts[2]}"
        assert parts[3] == category, f"Fourth part should be category '{category}': {parts[3]}"
        assert parts[4] == name, f"Fifth part should be name '{name}': {parts[4]}"
    
    @given(env=env_strategy)
    @settings(max_examples=20)
    def test_secret_names_follow_convention(self, env: str):
        """
        Property 10.4: All secret names follow the pattern
        call-processing/{env}/{name}
        """
        naming = ResourceNaming(env)
        pattern = re.compile(rf"^call-processing/{env}/[a-z0-9-]+$")
        
        for secret_name in naming.all_secrets():
            assert pattern.match(secret_name), (
                f"Secret name '{secret_name}' does not match pattern for env '{env}'"
            )
    
    @given(env=env_strategy)
    @settings(max_examples=20)
    def test_glue_database_names_follow_convention(self, env: str):
        """
        Property 10.5: Glue database names follow the pattern
        call-processing-{env}-analytics
        """
        naming = ResourceNaming(env)
        db_name = naming.glue_database()
        
        expected = f"call-processing-{env}-analytics"
        assert db_name == expected, (
            f"Glue database name '{db_name}' should be '{expected}'"
        )
    
    @given(env=env_strategy)
    @settings(max_examples=20)
    def test_cloudwatch_log_group_names_follow_convention(self, env: str):
        """
        Property 10.6: CloudWatch log group names follow the pattern
        /aws/call-processing/{env}
        """
        naming = ResourceNaming(env)
        log_group = naming.log_group()
        
        expected = f"/aws/call-processing/{env}"
        assert log_group == expected, (
            f"Log group name '{log_group}' should be '{expected}'"
        )
    
    @given(env=env_strategy)
    @settings(max_examples=20)
    def test_all_resource_names_contain_environment(self, env: str):
        """
        Property 10.7: All resource names contain the environment identifier.
        """
        naming = ResourceNaming(env)
        
        # DynamoDB tables
        for table in naming.all_dynamodb_tables():
            assert env in table, f"Table '{table}' missing environment '{env}'"
        
        # S3 buckets
        for bucket in naming.all_s3_buckets():
            assert env in bucket, f"Bucket '{bucket}' missing environment '{env}'"
        
        # Secrets
        for secret in naming.all_secrets():
            assert env in secret, f"Secret '{secret}' missing environment '{env}'"
        
        # Glue database
        assert env in naming.glue_database(), (
            f"Glue database '{naming.glue_database()}' missing environment '{env}'"
        )
        
        # CloudWatch log group
        assert env in naming.log_group(), (
            f"Log group '{naming.log_group()}' missing environment '{env}'"
        )
    
    @given(env=env_strategy)
    @settings(max_examples=20)
    def test_all_resource_names_contain_capability(self, env: str):
        """
        Property 10.8: All resource names contain the capability identifier 'call-processing'.
        """
        naming = ResourceNaming(env)
        capability = "call-processing"
        
        # DynamoDB tables
        for table in naming.all_dynamodb_tables():
            assert capability in table, f"Table '{table}' missing capability '{capability}'"
        
        # S3 buckets
        for bucket in naming.all_s3_buckets():
            assert capability in bucket, f"Bucket '{bucket}' missing capability '{capability}'"
        
        # Secrets
        for secret in naming.all_secrets():
            assert capability in secret, f"Secret '{secret}' missing capability '{capability}'"
        
        # Glue database
        assert capability in naming.glue_database(), (
            f"Glue database '{naming.glue_database()}' missing capability '{capability}'"
        )
        
        # CloudWatch log group
        assert capability in naming.log_group(), (
            f"Log group '{naming.log_group()}' missing capability '{capability}'"
        )


class TestNamingUniqueness:
    """Tests for resource name uniqueness across environments."""
    
    def test_resource_names_unique_across_environments(self):
        """
        All resource names should be unique across different environments.
        """
        all_names = {}
        
        for env in VALID_ENVIRONMENTS:
            naming = ResourceNaming(env)
            
            # Collect all resource names
            names = set()
            names.update(naming.all_dynamodb_tables())
            names.update(naming.all_s3_buckets())
            names.update(naming.all_secrets())
            names.add(naming.glue_database())
            names.add(naming.log_group())
            
            # Check for collisions with other environments
            for name in names:
                if name in all_names:
                    pytest.fail(
                        f"Name collision: '{name}' exists in both "
                        f"'{all_names[name]}' and '{env}'"
                    )
                all_names[name] = env
    
    def test_no_duplicate_names_within_environment(self):
        """
        No duplicate resource names within the same environment.
        """
        for env in VALID_ENVIRONMENTS:
            naming = ResourceNaming(env)
            
            all_names = []
            all_names.extend(naming.all_dynamodb_tables())
            all_names.extend(naming.all_s3_buckets())
            all_names.extend(naming.all_secrets())
            all_names.append(naming.glue_database())
            all_names.append(naming.log_group())
            
            # Check for duplicates
            seen = set()
            for name in all_names:
                assert name not in seen, (
                    f"Duplicate resource name '{name}' in environment '{env}'"
                )
                seen.add(name)


class TestNamingSpecificResources:
    """Tests for specific resource naming requirements."""
    
    @pytest.mark.parametrize("env", list(VALID_ENVIRONMENTS))
    def test_expected_dynamodb_tables(self, env: str):
        """Verify all expected DynamoDB tables are named correctly."""
        naming = ResourceNaming(env)
        tables = naming.all_dynamodb_tables()
        
        expected_suffixes = ["transformation-system", "license", "wxcc-task-tracking", "lead-opportunity-tracking"]
        for suffix in expected_suffixes:
            expected_name = f"call-processing-{env}-{suffix}"
            assert expected_name in tables, (
                f"Missing expected table '{expected_name}'"
            )
    
    @pytest.mark.parametrize("env", list(VALID_ENVIRONMENTS))
    def test_expected_s3_buckets(self, env: str):
        """Verify all expected S3 buckets are named correctly."""
        naming = ResourceNaming(env)
        buckets = naming.all_s3_buckets()
        
        expected_suffixes = ["call-data", "wxcc-simulator", "journey-logs", "journey-reports"]
        for suffix in expected_suffixes:
            expected_name = f"call-processing-{env}-{suffix}"
            assert expected_name in buckets, (
                f"Missing expected bucket '{expected_name}'"
            )
    
    @pytest.mark.parametrize("env", list(VALID_ENVIRONMENTS))
    def test_expected_secrets(self, env: str):
        """Verify all expected secrets are named correctly."""
        naming = ResourceNaming(env)
        secrets = naming.all_secrets()
        
        expected_names = ["api-keys", "wxcc", "openai", "license", "anthropic", "github"]
        for name in expected_names:
            expected_secret = f"call-processing/{env}/{name}"
            assert expected_secret in secrets, (
                f"Missing expected secret '{expected_secret}'"
            )
