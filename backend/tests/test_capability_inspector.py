"""
Tests for CapabilityInspector (smoke-level - inspector aggregates 17
sections and produces a single report; per-section deep tests would be
mostly mock plumbing. We verify the orchestration shape: sections
returned, parallel section completion, and that an exception in one
section does not poison the rest).
"""
from unittest.mock import MagicMock, patch

import pytest

from app.services.capability_inspector import CapabilityInspector


def _make_inspector():
    return CapabilityInspector(
        core_v1=MagicMock(),
        apps_v1=MagicMock(),
        custom=MagicMock(),
        eks_client=MagicMock(),
        iam_client=MagicMock(),
        sts_client=MagicMock(),
        boto3_session=MagicMock(),
        region="us-east-1",
        cluster_name="c",
        namespace="myns",
        capability_name="cp",
        environment="test",
        cr_name="cp-test",
        account_id="111",
    )


def test_section_kubernetes_resources_returns_summary():
    inspector = _make_inspector()
    inspector.apps_v1.list_namespaced_deployment.return_value = MagicMock(items=[])
    inspector.apps_v1.list_namespaced_stateful_set.return_value = MagicMock(items=[])
    inspector.core_v1.list_namespaced_pod.return_value = MagicMock(items=[])
    inspector.core_v1.list_namespaced_service.return_value = MagicMock(items=[])
    sec = inspector.section_kubernetes_resources()
    assert sec.name == "k8s_resources"
    assert sec.label.startswith("Kubernetes")


def test_section_dynamodb_filters_by_capability_prefix():
    inspector = _make_inspector()
    ddb = MagicMock()
    paginator = MagicMock()
    paginator.paginate.return_value = [
        {"TableNames": ["cp-test-foo", "other-table"]},
    ]
    ddb.get_paginator.return_value = paginator
    ddb.describe_table.return_value = {"Table": {"TableStatus": "ACTIVE", "ItemCount": 0}}
    inspector.boto.client.return_value = ddb
    sec = inspector.section_dynamodb()
    names = [r.get("name") for r in sec.rows if "name" in r]
    assert "cp-test-foo" in names
    assert "other-table" not in names


@pytest.mark.asyncio
async def test_run_full_returns_all_sections_and_isolates_failures():
    inspector = _make_inspector()
    # Force one section to throw via mock side_effect; verify report
    # still contains all sections.
    inspector.section_dynamodb = MagicMock(side_effect=RuntimeError("ddb boom"))
    # Stub the rest to return minimal sections to avoid hitting AWS.
    from app.models.eks_pipeline import InspectionSection

    def stub(name, label):
        return lambda: InspectionSection(
            name=name, label=label, status="pass", summary="stub", rows=[]
        )

    for fn_name in [
        "section_kubernetes_resources", "section_service_versions",
        "section_s3", "section_glue",
        "section_athena_workgroup", "section_athena_deep",
        "section_ssm", "section_secrets", "section_iam", "section_cognito",
        "section_alb", "section_wxcc", "section_licensing",
        "section_call_processing", "section_app_perms_vpce",
        "section_call_db_doctor",
    ]:
        setattr(inspector, fn_name, stub(fn_name.replace("section_", ""), fn_name))

    report = await inspector.run_full()
    # 16 stubbed + 1 raised = 17 sections worth of entries; raised one
    # turns into an "error" InspectionSection.
    assert len(report.sections) >= 16
    assert any(s.status == "fail" for s in report.sections)
