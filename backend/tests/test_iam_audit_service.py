"""Tests for IamAuditService (managed + preprovisioned modes)."""
from unittest.mock import MagicMock

import pytest

from app.services.iam_audit_service import IamAuditService


def test_managed_mode_all_actions_allowed_returns_pass():
    iam = MagicMock()
    sts = MagicMock()
    sts.get_caller_identity.return_value = {
        "Account": "111", "Arn": "arn:aws:iam::111:role/Deployer",
    }
    iam.simulate_principal_policy.return_value = {
        "EvaluationResults": [
            {"EvalActionName": a, "EvalDecision": "allowed"}
            for a in ["iam:CreateRole", "iam:GetRole"]
        ],
    }
    auditor = IamAuditService(iam_client=iam, sts_client=sts)
    report = auditor.audit(
        iam_mode="managed",
        oidc_provider_id="oidc/id/X",
        cluster_name="c",
    )
    assert report.iam_mode == "managed"
    assert report.overall == "pass"
    assert report.can_proceed is True


def test_managed_mode_some_denied_returns_fail():
    iam = MagicMock()
    sts = MagicMock()
    sts.get_caller_identity.return_value = {
        "Account": "111", "Arn": "arn:aws:iam::111:role/Deployer",
    }
    iam.simulate_principal_policy.return_value = {
        "EvaluationResults": [
            {"EvalActionName": "iam:CreateRole", "EvalDecision": "explicitDeny"},
            {"EvalActionName": "iam:GetRole", "EvalDecision": "allowed"},
        ],
    }
    auditor = IamAuditService(iam_client=iam, sts_client=sts)
    report = auditor.audit(
        iam_mode="managed",
        oidc_provider_id="oidc/id/X",
        cluster_name="c",
    )
    assert report.overall == "fail"
    assert report.can_proceed is False


def test_managed_mode_simulate_unavailable_softens_to_warn():
    from botocore.exceptions import ClientError

    iam = MagicMock()
    sts = MagicMock()
    sts.get_caller_identity.return_value = {
        "Account": "111", "Arn": "arn:aws:iam::111:role/Deployer",
    }
    iam.simulate_principal_policy.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "x"}}, "SimulatePrincipalPolicy",
    )
    auditor = IamAuditService(iam_client=iam, sts_client=sts)
    report = auditor.audit(
        iam_mode="managed",
        oidc_provider_id="oidc/id/X",
        cluster_name="c",
    )
    assert report.overall == "warn"
    assert report.can_proceed is True


def test_preprovisioned_missing_role_returns_fail():
    from botocore.exceptions import ClientError

    iam = MagicMock()
    iam.get_role.side_effect = ClientError(
        {"Error": {"Code": "NoSuchEntity", "Message": "x"}}, "GetRole",
    )
    auditor = IamAuditService(iam_client=iam, sts_client=MagicMock())
    report = auditor.audit(
        iam_mode="preprovisioned",
        oidc_provider_id="oidc/id/X",
        cluster_name="c",
    )
    assert report.iam_mode == "preprovisioned"
    assert report.overall == "fail"
    assert report.can_proceed is False
