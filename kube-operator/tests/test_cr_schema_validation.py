"""
Smoke test that every example CR validates against the live CRD schema.

Catches schema-drift regressions like the Cognito case where examples used
top-level keys not declared in the CRD's OpenAPI.
"""
import os
import sys
from pathlib import Path

import pytest
import yaml

# jsonschema is a dependency of openapi-schema-validator and ships with
# the kubernetes Python package; if absent, skip rather than fail noisily.
jsonschema = pytest.importorskip("jsonschema")


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = REPO_ROOT / "examples"
CRD_PATH = REPO_ROOT / "manifests" / "crd.yaml"


def _load_schema():
    with CRD_PATH.open() as f:
        crd = yaml.safe_load(f)
    versions = crd["spec"]["versions"]
    schema = versions[0]["schema"]["openAPIV3Schema"]
    # Validate just the spec sub-schema; metadata/apiVersion/kind are
    # k8s-managed and not under our control.
    return schema["properties"]["spec"]


def _example_files():
    files = []
    for path in EXAMPLES_DIR.glob("*.yaml"):
        if path.name == "README.md":
            continue
        files.append(path)
    return files


@pytest.mark.parametrize("example_path", _example_files())
def test_example_validates_against_crd(example_path):
    spec_schema = _load_schema()

    with example_path.open() as f:
        # Some examples are multi-document (e.g. include CronJob templates);
        # only validate the TotogiCapability ones.
        for doc in yaml.safe_load_all(f):
            if not isinstance(doc, dict):
                continue
            if doc.get("kind") != "TotogiCapability":
                continue
            jsonschema.validate(instance=doc.get("spec", {}), schema=spec_schema)
