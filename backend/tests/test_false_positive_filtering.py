"""
Unit Tests for False Positive Filtering
Tests that valid resource references are not flagged as undefined parameters.

Feature: deployment-prerequisites-verification
Requirements: 4.4
"""
import pytest

from app.services.reference_validator import ReferenceValidator, PSEUDO_PARAMETERS
from app.services.template_validator import TemplateValidator
from app.services.pre_deployment_checker import PreDeploymentChecker
from app.utils.cfn_yaml_loader import CFNTag


class TestFalsePositiveFiltering:
    """Tests for filtering false positive warnings."""
    
    def test_ref_to_vpc_resource_not_flagged(self):
        """!Ref to VPC resource should not be flagged as undefined parameter."""
        validator = ReferenceValidator()
        
        template = {
            'Resources': {
                'VPC': {'Type': 'AWS::EC2::VPC'},
                'Subnet': {
                    'Type': 'AWS::EC2::Subnet',
                    'Properties': {
                        'VpcId': CFNTag('Ref', 'VPC')
                    }
                }
            }
        }
        
        result = validator.validate_all_references(template)
        
        assert result.success is True
        assert len(result.invalid_refs) == 0
        assert 'VPC' in result.valid_resource_refs
    
    def test_ref_to_security_group_not_flagged(self):
        """!Ref to SecurityGroup resource should not be flagged."""
        validator = ReferenceValidator()
        
        template = {
            'Resources': {
                'ALBSecurityGroup': {'Type': 'AWS::EC2::SecurityGroup'},
                'ECSSecurityGroup': {'Type': 'AWS::EC2::SecurityGroup'},
                'ECSService': {
                    'Type': 'AWS::ECS::Service',
                    'Properties': {
                        'NetworkConfiguration': {
                            'SecurityGroups': [
                                CFNTag('Ref', 'ALBSecurityGroup'),
                                CFNTag('Ref', 'ECSSecurityGroup')
                            ]
                        }
                    }
                }
            }
        }
        
        result = validator.validate_all_references(template)
        
        assert result.success is True
        assert 'ALBSecurityGroup' in result.valid_resource_refs
        assert 'ECSSecurityGroup' in result.valid_resource_refs
    
    def test_ref_to_subnet_not_flagged(self):
        """!Ref to Subnet resources should not be flagged."""
        validator = ReferenceValidator()
        
        template = {
            'Resources': {
                'PublicSubnet1': {'Type': 'AWS::EC2::Subnet'},
                'PublicSubnet2': {'Type': 'AWS::EC2::Subnet'},
                'PrivateSubnet1': {'Type': 'AWS::EC2::Subnet'},
                'PrivateSubnet2': {'Type': 'AWS::EC2::Subnet'},
                'LoadBalancer': {
                    'Type': 'AWS::ElasticLoadBalancingV2::LoadBalancer',
                    'Properties': {
                        'Subnets': [
                            CFNTag('Ref', 'PublicSubnet1'),
                            CFNTag('Ref', 'PublicSubnet2')
                        ]
                    }
                }
            }
        }
        
        result = validator.validate_all_references(template)
        
        assert result.success is True
        assert 'PublicSubnet1' in result.valid_resource_refs
        assert 'PublicSubnet2' in result.valid_resource_refs
    
    def test_filter_false_positives_from_warnings(self):
        """filter_false_positives correctly separates valid refs from truly undefined."""
        validator = ReferenceValidator()
        
        # Simulate warnings from template_validator
        warnings = [
            "Resources.Subnet.Properties.VpcId.Ref: VPC",
            "Resources.SG.Properties.VpcId.Ref: VPC",
            "Resources.Instance.Properties.SubnetId.Ref: PublicSubnet1",
            "Resources.Lambda.Properties.RoleArn.Ref: UndefinedRole",
            "Resources.Task.Properties.ExecutionRoleArn.Ref: NonExistentRole"
        ]
        
        template = {
            'Resources': {
                'VPC': {'Type': 'AWS::EC2::VPC'},
                'PublicSubnet1': {'Type': 'AWS::EC2::Subnet'},
                'Subnet': {'Type': 'AWS::EC2::Subnet'},
                'SG': {'Type': 'AWS::EC2::SecurityGroup'},
                'Instance': {'Type': 'AWS::EC2::Instance'},
                'Lambda': {'Type': 'AWS::Lambda::Function'},
                'Task': {'Type': 'AWS::ECS::TaskDefinition'}
            }
        }
        
        truly_undefined, valid_refs = validator.filter_false_positives(warnings, template)
        
        # VPC and PublicSubnet1 should be filtered out
        assert 'VPC' in valid_refs
        assert 'PublicSubnet1' in valid_refs
        
        # UndefinedRole and NonExistentRole should remain
        assert len(truly_undefined) == 2
        assert any('UndefinedRole' in w for w in truly_undefined)
        assert any('NonExistentRole' in w for w in truly_undefined)
    
    def test_pseudo_parameters_not_flagged(self):
        """Pseudo-parameters like AWS::StackName should not be flagged."""
        validator = ReferenceValidator()
        
        template = {
            'Resources': {
                'Bucket': {
                    'Type': 'AWS::S3::Bucket',
                    'Properties': {
                        'BucketName': CFNTag('Sub', '${AWS::StackName}-${AWS::Region}-bucket')
                    }
                }
            }
        }
        
        result = validator.validate_all_references(template)
        
        assert result.success is True
        assert len(result.invalid_refs) == 0
    
    def test_all_pseudo_parameters_recognized(self):
        """All CloudFormation pseudo-parameters are recognized."""
        validator = ReferenceValidator()
        
        for pseudo in PSEUDO_PARAMETERS:
            assert validator.is_pseudo_parameter(pseudo) is True
            
            is_valid, issue = validator.validate_ref(
                pseudo,
                defined_parameters=set(),
                defined_resources=set()
            )
            assert is_valid is True, f"Pseudo-parameter {pseudo} should be valid"


class TestTemplateValidatorFix:
    """Tests that template_validator.validate_conditions is fixed."""
    
    def test_validate_conditions_no_false_positives(self):
        """validate_conditions should not flag valid resource refs."""
        validator = TemplateValidator()
        
        template = {
            'Parameters': {
                'Environment': {'Type': 'String'}
            },
            'Conditions': {
                'IsProd': {
                    'Fn::Equals': [CFNTag('Ref', 'Environment'), 'prod']
                }
            },
            'Resources': {
                'VPC': {'Type': 'AWS::EC2::VPC'},
                'Subnet': {
                    'Type': 'AWS::EC2::Subnet',
                    'Properties': {
                        'VpcId': CFNTag('Ref', 'VPC')
                    }
                }
            }
        }
        
        result = validator.validate_conditions(template)
        
        # VPC should NOT be in undefined_parameters
        assert 'VPC' not in str(result.undefined_parameters)
        
        # Environment is a valid parameter, should not be flagged
        assert 'Environment' not in str(result.undefined_parameters)


class TestPreDeploymentCheckerIntegration:
    """Integration tests for PreDeploymentChecker with false positive fix."""
    
    def test_comprehensive_template_no_false_positives(self):
        """Comprehensive template validation produces no false positive warnings."""
        # This simulates the exact scenario that was causing 74 false positive warnings
        template = {
            'AWSTemplateFormatVersion': '2010-09-09',
            'Parameters': {
                'Environment': {'Type': 'String', 'Default': 'dev'},
                'LogRetentionDays': {
                    'Type': 'Number',
                    'Default': 30,
                    'AllowedValues': [1, 3, 5, 7, 14, 30, 60, 90]
                }
            },
            'Resources': {
                'VPC': {
                    'Type': 'AWS::EC2::VPC',
                    'Properties': {'CidrBlock': '10.0.0.0/16'}
                },
                'PublicSubnet1': {
                    'Type': 'AWS::EC2::Subnet',
                    'Properties': {
                        'VpcId': CFNTag('Ref', 'VPC'),
                        'CidrBlock': '10.0.1.0/24'
                    }
                },
                'PublicSubnet2': {
                    'Type': 'AWS::EC2::Subnet',
                    'Properties': {
                        'VpcId': CFNTag('Ref', 'VPC'),
                        'CidrBlock': '10.0.2.0/24'
                    }
                },
                'InternetGateway': {
                    'Type': 'AWS::EC2::InternetGateway'
                },
                'VPCGatewayAttachment': {
                    'Type': 'AWS::EC2::VPCGatewayAttachment',
                    'Properties': {
                        'VpcId': CFNTag('Ref', 'VPC'),
                        'InternetGatewayId': CFNTag('Ref', 'InternetGateway')
                    }
                },
                'ALBSecurityGroup': {
                    'Type': 'AWS::EC2::SecurityGroup',
                    'Properties': {
                        'VpcId': CFNTag('Ref', 'VPC'),
                        'GroupDescription': 'ALB Security Group'
                    }
                },
                'ECSSecurityGroup': {
                    'Type': 'AWS::EC2::SecurityGroup',
                    'Properties': {
                        'VpcId': CFNTag('Ref', 'VPC'),
                        'GroupDescription': 'ECS Security Group'
                    }
                },
                'ApplicationLoadBalancer': {
                    'Type': 'AWS::ElasticLoadBalancingV2::LoadBalancer',
                    'Properties': {
                        'Subnets': [
                            CFNTag('Ref', 'PublicSubnet1'),
                            CFNTag('Ref', 'PublicSubnet2')
                        ],
                        'SecurityGroups': [CFNTag('Ref', 'ALBSecurityGroup')]
                    }
                },
                'ECSCluster': {
                    'Type': 'AWS::ECS::Cluster'
                },
                'TaskDefinition': {
                    'Type': 'AWS::ECS::TaskDefinition',
                    'Properties': {
                        'Family': CFNTag('Sub', '${AWS::StackName}-task')
                    }
                },
                'ECSService': {
                    'Type': 'AWS::ECS::Service',
                    'Properties': {
                        'Cluster': CFNTag('Ref', 'ECSCluster'),
                        'TaskDefinition': CFNTag('Ref', 'TaskDefinition'),
                        'NetworkConfiguration': {
                            'AwsvpcConfiguration': {
                                'Subnets': [
                                    CFNTag('Ref', 'PublicSubnet1'),
                                    CFNTag('Ref', 'PublicSubnet2')
                                ],
                                'SecurityGroups': [CFNTag('Ref', 'ECSSecurityGroup')]
                            }
                        }
                    }
                }
            }
        }
        
        # Validate with ReferenceValidator
        ref_validator = ReferenceValidator()
        result = ref_validator.validate_all_references(template)
        
        assert result.success is True
        assert len(result.invalid_refs) == 0
        assert len(result.invalid_getatt) == 0
        
        # All these should be recognized as valid resource refs
        expected_resource_refs = {
            'VPC', 'PublicSubnet1', 'PublicSubnet2', 'InternetGateway',
            'ALBSecurityGroup', 'ECSSecurityGroup', 'ECSCluster', 'TaskDefinition'
        }
        
        for ref in expected_resource_refs:
            assert ref in result.valid_resource_refs, f"{ref} should be a valid resource ref"
