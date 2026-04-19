"""
Property Tests for Cross-Stack Dependency Checker
Tests validation of CloudFormation cross-stack dependencies.

Feature: deployment-prerequisites-verification
Requirements: 2.1, 2.2, 2.3
"""
import pytest
from hypothesis import given, strategies as st, assume, settings

from app.services.cross_stack_dependency_checker import (
    CrossStackDependencyChecker,
    StackExport,
    StackImport,
    MissingExport,
    CrossStackDependencyResult
)
from app.utils.cfn_yaml_loader import CFNTag


class TestCrossStackDependencyDetection:
    """Property 8: Cross-Stack Dependency Detection (Requirements 2.1, 2.2, 2.3)"""
    
    def test_export_extraction_from_outputs(self):
        """Exports are correctly extracted from Outputs section."""
        checker = CrossStackDependencyChecker()
        
        template = {
            'Outputs': {
                'VpcId': {
                    'Value': CFNTag('Ref', 'VPC'),
                    'Export': {'Name': 'MyStack-VpcId'}
                },
                'SubnetId': {
                    'Value': CFNTag('GetAtt', ['Subnet', 'SubnetId']),
                    'Export': {'Name': 'MyStack-SubnetId'}
                },
                'NoExport': {
                    'Value': 'some-value'
                }
            }
        }
        
        exports = checker.extract_exports(template, 'MyStack')
        
        assert len(exports) == 2
        export_names = {e.export_name for e in exports}
        assert 'MyStack-VpcId' in export_names
        assert 'MyStack-SubnetId' in export_names
    
    def test_import_extraction_from_template(self):
        """ImportValue references are correctly extracted."""
        checker = CrossStackDependencyChecker()
        
        template = {
            'Resources': {
                'SecurityGroup': {
                    'Type': 'AWS::EC2::SecurityGroup',
                    'Properties': {
                        'VpcId': CFNTag('ImportValue', 'NetworkStack-VpcId'),
                        'GroupDescription': 'Test SG'
                    }
                },
                'Instance': {
                    'Type': 'AWS::EC2::Instance',
                    'Properties': {
                        'SubnetId': CFNTag('ImportValue', 'NetworkStack-SubnetId')
                    }
                }
            }
        }
        
        imports = checker.extract_imports(template, 'AppStack')
        
        assert len(imports) == 2
        import_names = {i.import_name for i in imports}
        assert 'NetworkStack-VpcId' in import_names
        assert 'NetworkStack-SubnetId' in import_names
    
    def test_dependency_graph_construction(self):
        """Dependency graph correctly maps imports to exports."""
        checker = CrossStackDependencyChecker()
        
        templates = {
            'NetworkStack': {
                'Resources': {'VPC': {'Type': 'AWS::EC2::VPC'}},
                'Outputs': {
                    'VpcId': {
                        'Value': CFNTag('Ref', 'VPC'),
                        'Export': {'Name': 'Network-VpcId'}
                    }
                }
            },
            'AppStack': {
                'Resources': {
                    'SG': {
                        'Type': 'AWS::EC2::SecurityGroup',
                        'Properties': {
                            'VpcId': CFNTag('ImportValue', 'Network-VpcId')
                        }
                    }
                }
            }
        }
        
        graph, export_map = checker.build_dependency_graph(templates)
        
        # AppStack depends on NetworkStack
        assert 'AppStack' in graph
        assert 'NetworkStack' in graph['AppStack']
    
    def test_missing_export_detection(self):
        """Missing exports are correctly detected."""
        checker = CrossStackDependencyChecker()
        
        templates = {
            'AppStack': {
                'Resources': {
                    'SG': {
                        'Type': 'AWS::EC2::SecurityGroup',
                        'Properties': {
                            'VpcId': CFNTag('ImportValue', 'NonExistent-VpcId')
                        }
                    }
                }
            }
        }
        
        result = checker.check_dependencies(templates)
        
        assert result.success is False
        assert len(result.missing_exports) == 1
        assert result.missing_exports[0].import_name == 'NonExistent-VpcId'
    
    def test_circular_dependency_detection(self):
        """Circular dependencies are correctly detected."""
        checker = CrossStackDependencyChecker()
        
        # Create a circular dependency: A -> B -> C -> A
        templates = {
            'StackA': {
                'Resources': {'R': {'Type': 'AWS::CloudFormation::WaitConditionHandle'}},
                'Outputs': {
                    'Out': {'Value': 'a', 'Export': {'Name': 'A-Export'}}
                }
            },
            'StackB': {
                'Resources': {
                    'R': {
                        'Type': 'AWS::CloudFormation::WaitConditionHandle',
                        'Properties': {'X': CFNTag('ImportValue', 'A-Export')}
                    }
                },
                'Outputs': {
                    'Out': {'Value': 'b', 'Export': {'Name': 'B-Export'}}
                }
            },
            'StackC': {
                'Resources': {
                    'R': {
                        'Type': 'AWS::CloudFormation::WaitConditionHandle',
                        'Properties': {'X': CFNTag('ImportValue', 'B-Export')}
                    }
                },
                'Outputs': {
                    'Out': {'Value': 'c', 'Export': {'Name': 'C-Export'}}
                }
            }
        }
        
        # Add circular dependency: StackA imports from StackC
        templates['StackA']['Resources']['R2'] = {
            'Type': 'AWS::CloudFormation::WaitConditionHandle',
            'Properties': {'X': CFNTag('ImportValue', 'C-Export')}
        }
        
        result = checker.check_dependencies(templates)
        
        assert len(result.circular_dependencies) > 0
    
    def test_deployment_order_respects_dependencies(self):
        """Deployment order puts dependencies before dependents."""
        checker = CrossStackDependencyChecker()
        
        templates = {
            'NetworkStack': {
                'Resources': {'VPC': {'Type': 'AWS::EC2::VPC'}},
                'Outputs': {
                    'VpcId': {'Value': CFNTag('Ref', 'VPC'), 'Export': {'Name': 'VpcId'}}
                }
            },
            'DatabaseStack': {
                'Resources': {
                    'DB': {
                        'Type': 'AWS::RDS::DBInstance',
                        'Properties': {'VpcId': CFNTag('ImportValue', 'VpcId')}
                    }
                },
                'Outputs': {
                    'DbEndpoint': {'Value': 'endpoint', 'Export': {'Name': 'DbEndpoint'}}
                }
            },
            'AppStack': {
                'Resources': {
                    'App': {
                        'Type': 'AWS::ECS::Service',
                        'Properties': {
                            'VpcId': CFNTag('ImportValue', 'VpcId'),
                            'DbEndpoint': CFNTag('ImportValue', 'DbEndpoint')
                        }
                    }
                }
            }
        }
        
        result = checker.check_dependencies(templates)
        
        # NetworkStack should come before DatabaseStack and AppStack
        network_idx = result.deployment_order.index('NetworkStack')
        db_idx = result.deployment_order.index('DatabaseStack')
        app_idx = result.deployment_order.index('AppStack')
        
        assert network_idx < db_idx
        assert network_idx < app_idx
        assert db_idx < app_idx
    
    def test_existing_exports_satisfy_imports(self):
        """Existing AWS exports satisfy import requirements."""
        checker = CrossStackDependencyChecker()
        
        templates = {
            'AppStack': {
                'Resources': {
                    'SG': {
                        'Type': 'AWS::EC2::SecurityGroup',
                        'Properties': {
                            'VpcId': CFNTag('ImportValue', 'ExistingStack-VpcId')
                        }
                    }
                }
            }
        }
        
        # Simulate existing export in AWS
        existing_exports = {'ExistingStack-VpcId'}
        
        result = checker.check_dependencies(templates, existing_exports)
        
        assert result.success is True
        assert len(result.missing_exports) == 0
    
    def test_no_dependencies_all_stacks_in_order(self):
        """Stacks with no dependencies are all included in deployment order."""
        checker = CrossStackDependencyChecker()
        
        templates = {
            'Stack1': {'Resources': {'R': {'Type': 'AWS::S3::Bucket'}}},
            'Stack2': {'Resources': {'R': {'Type': 'AWS::S3::Bucket'}}},
            'Stack3': {'Resources': {'R': {'Type': 'AWS::S3::Bucket'}}}
        }
        
        result = checker.check_dependencies(templates)
        
        assert result.success is True
        assert set(result.deployment_order) == {'Stack1', 'Stack2', 'Stack3'}


class TestExportExtraction:
    """Tests for export extraction edge cases."""
    
    def test_dynamic_export_name_with_sub(self):
        """Dynamic export names using !Sub are handled."""
        checker = CrossStackDependencyChecker()
        
        template = {
            'Outputs': {
                'VpcId': {
                    'Value': CFNTag('Ref', 'VPC'),
                    'Export': {'Name': CFNTag('Sub', '${AWS::StackName}-VpcId')}
                }
            }
        }
        
        exports = checker.extract_exports(template, 'TestStack')
        
        assert len(exports) == 1
        assert exports[0].export_name.startswith('<dynamic:')
    
    def test_empty_outputs_section(self):
        """Empty outputs section returns no exports."""
        checker = CrossStackDependencyChecker()
        
        template = {'Resources': {'R': {'Type': 'AWS::S3::Bucket'}}}
        
        exports = checker.extract_exports(template, 'TestStack')
        
        assert len(exports) == 0


class TestImportExtraction:
    """Tests for import extraction edge cases."""
    
    def test_nested_import_value(self):
        """ImportValue nested in other intrinsic functions is found."""
        checker = CrossStackDependencyChecker()
        
        template = {
            'Resources': {
                'R': {
                    'Type': 'AWS::Lambda::Function',
                    'Properties': {
                        'Environment': {
                            'Variables': {
                                'VPC_ID': CFNTag('ImportValue', 'Network-VpcId')
                            }
                        }
                    }
                }
            }
        }
        
        imports = checker.extract_imports(template, 'AppStack')
        
        assert len(imports) == 1
        assert imports[0].import_name == 'Network-VpcId'
    
    def test_no_imports_in_template(self):
        """Template with no imports returns empty list."""
        checker = CrossStackDependencyChecker()
        
        template = {
            'Resources': {
                'Bucket': {
                    'Type': 'AWS::S3::Bucket',
                    'Properties': {'BucketName': 'my-bucket'}
                }
            }
        }
        
        imports = checker.extract_imports(template, 'TestStack')
        
        assert len(imports) == 0
