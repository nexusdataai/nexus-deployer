"""
Property-based tests for Dependency Validator.

Feature: cloudformation-template-reliability
Property 4: Dependency Graph Correctly Models Stack Relationships

Validates: Requirements 4.1, 4.3, 4.4
"""
import pytest
from hypothesis import given, strategies as st, settings, assume

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.dependency_validator import (
    DependencyValidator,
    DependencyGraph,
    DependencyValidationResult
)
from app.utils.cfn_yaml_loader import CFNTag


# Strategies for generating test data
stack_names = st.text(
    min_size=1,
    max_size=20,
    alphabet=st.characters(whitelist_categories=('L', 'N'), whitelist_characters='-')
).filter(lambda x: x[0].isalpha() if x else False)

export_names = st.text(
    min_size=1,
    max_size=30,
    alphabet=st.characters(whitelist_categories=('L', 'N'), whitelist_characters='-:')
).filter(lambda x: x[0].isalpha() if x else False)


class TestDependencyGraphProperty:
    """
    Property 4: Dependency Graph Correctly Models Stack Relationships
    
    For any set of CloudFormation templates with ImportValue and Export
    declarations, the Dependency_Validator SHALL build a correct dependency
    graph and detect all circular dependencies.
    """
    
    def setup_method(self):
        self.validator = DependencyValidator()
    
    @given(
        stack_name=stack_names,
        export_name=export_names
    )
    @settings(max_examples=100)
    def test_extract_imports_finds_all_importvalue_references(
        self, stack_name: str, export_name: str
    ):
        """
        Requirement 4.1: All ImportValue references are identified.
        """
        template = {
            'Resources': {
                'MyResource': {
                    'Type': 'AWS::S3::Bucket',
                    'Properties': {
                        'BucketName': CFNTag('ImportValue', export_name)
                    }
                }
            }
        }
        
        imports = self.validator.extract_imports(template)
        
        assert export_name in imports
    
    @given(
        stack_name=stack_names,
        export_name=export_names
    )
    @settings(max_examples=100)
    def test_extract_exports_finds_all_export_names(
        self, stack_name: str, export_name: str
    ):
        """
        Requirement 4.1: All Export names are identified.
        """
        template = {
            'Resources': {
                'MyBucket': {'Type': 'AWS::S3::Bucket'}
            },
            'Outputs': {
                'BucketName': {
                    'Value': CFNTag('Ref', 'MyBucket'),
                    'Export': {'Name': export_name}
                }
            }
        }
        
        exports = self.validator.extract_exports(template)
        
        assert export_name in exports
    
    @given(
        stack1=stack_names,
        stack2=stack_names,
        export_name=export_names
    )
    @settings(max_examples=100)
    def test_dependency_graph_correctly_models_import_export_relationship(
        self, stack1: str, stack2: str, export_name: str
    ):
        """
        Requirement 4.3: Dependency graph correctly models stack relationships.
        """
        assume(stack1 != stack2)
        
        # Stack1 exports, Stack2 imports
        templates = {
            stack1: {
                'Resources': {
                    'MyBucket': {'Type': 'AWS::S3::Bucket'}
                },
                'Outputs': {
                    'BucketName': {
                        'Value': CFNTag('Ref', 'MyBucket'),
                        'Export': {'Name': export_name}
                    }
                }
            },
            stack2: {
                'Resources': {
                    'MyResource': {
                        'Type': 'AWS::Lambda::Function',
                        'Properties': {
                            'Environment': {
                                'Variables': {
                                    'BUCKET': CFNTag('ImportValue', export_name)
                                }
                            }
                        }
                    }
                }
            }
        }
        
        graph = self.validator.build_dependency_graph(templates)
        
        # Stack2 should depend on Stack1
        assert stack1 in graph.nodes
        assert stack2 in graph.nodes
        assert stack1 in graph.edges.get(stack2, set())
    
    def test_circular_dependency_detected_simple(self):
        """
        Requirement 4.4: Simple circular dependencies are detected.
        """
        # A -> B -> A
        templates = {
            'StackA': {
                'Resources': {
                    'Resource': {
                        'Type': 'AWS::S3::Bucket',
                        'Properties': {
                            'BucketName': CFNTag('ImportValue', 'ExportFromB')
                        }
                    }
                },
                'Outputs': {
                    'Output': {
                        'Value': 'value',
                        'Export': {'Name': 'ExportFromA'}
                    }
                }
            },
            'StackB': {
                'Resources': {
                    'Resource': {
                        'Type': 'AWS::S3::Bucket',
                        'Properties': {
                            'BucketName': CFNTag('ImportValue', 'ExportFromA')
                        }
                    }
                },
                'Outputs': {
                    'Output': {
                        'Value': 'value',
                        'Export': {'Name': 'ExportFromB'}
                    }
                }
            }
        }
        
        result = self.validator.validate_dependencies(templates)
        
        assert result.success is False
        assert len(result.circular_dependencies) > 0
    
    def test_circular_dependency_detected_complex(self):
        """
        Requirement 4.4: Complex circular dependencies (A -> B -> C -> A) are detected.
        """
        templates = {
            'StackA': {
                'Resources': {
                    'Resource': {
                        'Type': 'AWS::S3::Bucket',
                        'Properties': {
                            'BucketName': CFNTag('ImportValue', 'ExportFromC')
                        }
                    }
                },
                'Outputs': {
                    'Output': {
                        'Value': 'value',
                        'Export': {'Name': 'ExportFromA'}
                    }
                }
            },
            'StackB': {
                'Resources': {
                    'Resource': {
                        'Type': 'AWS::S3::Bucket',
                        'Properties': {
                            'BucketName': CFNTag('ImportValue', 'ExportFromA')
                        }
                    }
                },
                'Outputs': {
                    'Output': {
                        'Value': 'value',
                        'Export': {'Name': 'ExportFromB'}
                    }
                }
            },
            'StackC': {
                'Resources': {
                    'Resource': {
                        'Type': 'AWS::S3::Bucket',
                        'Properties': {
                            'BucketName': CFNTag('ImportValue', 'ExportFromB')
                        }
                    }
                },
                'Outputs': {
                    'Output': {
                        'Value': 'value',
                        'Export': {'Name': 'ExportFromC'}
                    }
                }
            }
        }
        
        result = self.validator.validate_dependencies(templates)
        
        assert result.success is False
        assert len(result.circular_dependencies) > 0
        # Cycle should include all three stacks
        cycle = result.circular_dependencies[0]
        assert len(cycle) >= 3
    
    def test_no_circular_dependency_linear_chain(self):
        """Linear dependency chain should not be detected as circular."""
        # A -> B -> C (no cycle)
        templates = {
            'StackA': {
                'Resources': {'Resource': {'Type': 'AWS::S3::Bucket'}},
                'Outputs': {
                    'Output': {
                        'Value': 'value',
                        'Export': {'Name': 'ExportFromA'}
                    }
                }
            },
            'StackB': {
                'Resources': {
                    'Resource': {
                        'Type': 'AWS::S3::Bucket',
                        'Properties': {
                            'BucketName': CFNTag('ImportValue', 'ExportFromA')
                        }
                    }
                },
                'Outputs': {
                    'Output': {
                        'Value': 'value',
                        'Export': {'Name': 'ExportFromB'}
                    }
                }
            },
            'StackC': {
                'Resources': {
                    'Resource': {
                        'Type': 'AWS::S3::Bucket',
                        'Properties': {
                            'BucketName': CFNTag('ImportValue', 'ExportFromB')
                        }
                    }
                }
            }
        }
        
        result = self.validator.validate_dependencies(templates)
        
        assert len(result.circular_dependencies) == 0
        # Deployment order should be A, B, C
        assert result.deployment_order.index('StackA') < result.deployment_order.index('StackB')
        assert result.deployment_order.index('StackB') < result.deployment_order.index('StackC')
    
    def test_missing_export_detected(self):
        """Missing exports should be detected."""
        templates = {
            'StackA': {
                'Resources': {
                    'Resource': {
                        'Type': 'AWS::S3::Bucket',
                        'Properties': {
                            'BucketName': CFNTag('ImportValue', 'NonExistentExport')
                        }
                    }
                }
            }
        }
        
        result = self.validator.validate_dependencies(templates)
        
        assert result.success is False
        assert len(result.missing_exports) > 0
        assert any(m.import_name == 'NonExistentExport' for m in result.missing_exports)
    
    def test_existing_exports_considered(self):
        """Existing exports should satisfy import requirements."""
        templates = {
            'StackA': {
                'Resources': {
                    'Resource': {
                        'Type': 'AWS::S3::Bucket',
                        'Properties': {
                            'BucketName': CFNTag('ImportValue', 'ExistingExport')
                        }
                    }
                }
            }
        }
        
        existing_exports = {'ExistingExport'}
        result = self.validator.validate_dependencies(templates, existing_exports)
        
        # Should not report missing export
        assert not any(m.import_name == 'ExistingExport' for m in result.missing_exports)


class TestDependencyGraphUnit:
    """Unit tests for DependencyGraph class."""
    
    def test_empty_graph_has_no_cycle(self):
        """Empty graph should have no cycles."""
        graph = DependencyGraph()
        has_cycle, cycle = graph.has_cycle()
        
        assert has_cycle is False
        assert cycle == []
    
    def test_single_node_no_cycle(self):
        """Single node with no edges should have no cycle."""
        graph = DependencyGraph()
        graph.add_node('A')
        
        has_cycle, cycle = graph.has_cycle()
        
        assert has_cycle is False
    
    def test_self_loop_detected(self):
        """Self-loop should be detected as cycle."""
        graph = DependencyGraph()
        graph.add_edge('A', 'A')
        
        has_cycle, cycle = graph.has_cycle()
        
        assert has_cycle is True
        assert 'A' in cycle
    
    def test_deployment_order_respects_dependencies(self):
        """Deployment order should respect dependencies."""
        graph = DependencyGraph()
        graph.add_edge('B', 'A')  # B depends on A
        graph.add_edge('C', 'B')  # C depends on B
        
        order = graph.get_deployment_order()
        
        # A should come before B, B should come before C
        assert order.index('A') < order.index('B')
        assert order.index('B') < order.index('C')
    
    def test_deployment_order_raises_on_cycle(self):
        """Deployment order should raise error on cycle."""
        graph = DependencyGraph()
        graph.add_edge('A', 'B')
        graph.add_edge('B', 'A')
        
        with pytest.raises(ValueError) as exc_info:
            graph.get_deployment_order()
        
        assert 'circular dependency' in str(exc_info.value).lower()


class TestImportExportExtraction:
    """Tests for import/export extraction."""
    
    def setup_method(self):
        self.validator = DependencyValidator()
    
    def test_nested_importvalue_extracted(self):
        """ImportValue nested in other structures should be extracted."""
        template = {
            'Resources': {
                'MyFunction': {
                    'Type': 'AWS::Lambda::Function',
                    'Properties': {
                        'Environment': {
                            'Variables': {
                                'VAR1': CFNTag('ImportValue', 'Export1'),
                                'VAR2': CFNTag('ImportValue', 'Export2')
                            }
                        },
                        'VpcConfig': {
                            'SubnetIds': [
                                CFNTag('ImportValue', 'Export3')
                            ]
                        }
                    }
                }
            }
        }
        
        imports = self.validator.extract_imports(template)
        
        assert 'Export1' in imports
        assert 'Export2' in imports
        assert 'Export3' in imports
    
    def test_long_form_importvalue_extracted(self):
        """Long-form Fn::ImportValue should be extracted."""
        template = {
            'Resources': {
                'MyResource': {
                    'Type': 'AWS::S3::Bucket',
                    'Properties': {
                        'BucketName': {'Fn::ImportValue': 'MyExport'}
                    }
                }
            }
        }
        
        imports = self.validator.extract_imports(template)
        
        assert 'MyExport' in imports
    
    def test_multiple_exports_extracted(self):
        """Multiple exports from same template should all be extracted."""
        template = {
            'Resources': {
                'Bucket1': {'Type': 'AWS::S3::Bucket'},
                'Bucket2': {'Type': 'AWS::S3::Bucket'}
            },
            'Outputs': {
                'Output1': {
                    'Value': CFNTag('Ref', 'Bucket1'),
                    'Export': {'Name': 'Export1'}
                },
                'Output2': {
                    'Value': CFNTag('Ref', 'Bucket2'),
                    'Export': {'Name': 'Export2'}
                },
                'Output3': {
                    'Value': 'static-value'
                    # No export
                }
            }
        }
        
        exports = self.validator.extract_exports(template)
        
        assert 'Export1' in exports
        assert 'Export2' in exports
        assert len(exports) == 2  # Output3 has no export
