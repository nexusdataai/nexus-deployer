"""Tests for IrsaMappingVerifier (trust policy + attached policy parsing)."""
from unittest.mock import MagicMock

import pytest

from app.services.irsa_mapping_verifier import IrsaMappingVerifier, IrsaRoleSpec


def _trust_policy(oidc_provider_id: str, sub: str):
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {
                "Federated": f"arn:aws:iam::111:oidc-provider/{oidc_provider_id}"
            },
            "Action": "sts:AssumeRoleWithWebIdentity",
            "Condition": {
                "StringEquals": {
                    f"{oidc_provider_id}:aud": "sts.amazonaws.com",
                    f"{oidc_provider_id}:sub": sub,
                }
            },
        }],
    }


def test_role_with_correct_trust_and_policies_passes():
    iam = MagicMock()
    oidc = "oidc.eks.us-east-1.amazonaws.com/id/ABC"
    iam.get_role.return_value = {
        "Role": {
            "Arn": "arn:aws:iam::111:role/foo",
            "AssumeRolePolicyDocument": _trust_policy(
                oidc, "system:serviceaccount:kube-system:my-sa",
            ),
        }
    }
    iam.list_attached_role_policies.return_value = {
        "AttachedPolicies": [{"PolicyArn": "arn:aws:iam::aws:policy/PolicyA"}]
    }
    iam.list_role_policies.return_value = {"PolicyNames": []}

    verifier = IrsaMappingVerifier(iam_client=iam, sts_client=MagicMock())
    spec = IrsaRoleSpec(
        name="foo", label="foo",
        role_name="foo", namespace="kube-system", service_account="my-sa",
        required_managed_policies=["arn:aws:iam::aws:policy/PolicyA"],
    )
    check = verifier.verify_role(spec, oidc)
    assert check.status == "pass"


def test_role_missing_policy_returns_warn():
    iam = MagicMock()
    oidc = "oidc/id/X"
    iam.get_role.return_value = {
        "Role": {
            "Arn": "arn:aws:iam::111:role/foo",
            "AssumeRolePolicyDocument": _trust_policy(
                oidc, "system:serviceaccount:kube-system:my-sa",
            ),
        }
    }
    iam.list_attached_role_policies.return_value = {"AttachedPolicies": []}
    iam.list_role_policies.return_value = {"PolicyNames": []}

    verifier = IrsaMappingVerifier(iam_client=iam, sts_client=MagicMock())
    spec = IrsaRoleSpec(
        name="foo", label="foo",
        role_name="foo", namespace="kube-system", service_account="my-sa",
        required_managed_policies=["arn:aws:iam::aws:policy/MissingPolicy"],
    )
    check = verifier.verify_role(spec, oidc)
    assert check.status == "warn"
    assert "missing required policies" in check.detail


def test_role_with_wrong_sub_returns_fail():
    iam = MagicMock()
    oidc = "oidc/id/X"
    iam.get_role.return_value = {
        "Role": {
            "Arn": "arn:aws:iam::111:role/foo",
            "AssumeRolePolicyDocument": _trust_policy(
                oidc, "system:serviceaccount:kube-system:WRONG_SA",
            ),
        }
    }
    iam.list_attached_role_policies.return_value = {"AttachedPolicies": []}
    iam.list_role_policies.return_value = {"PolicyNames": []}

    verifier = IrsaMappingVerifier(iam_client=iam, sts_client=MagicMock())
    spec = IrsaRoleSpec(
        name="foo", label="foo",
        role_name="foo", namespace="kube-system", service_account="my-sa",
    )
    check = verifier.verify_role(spec, oidc)
    assert check.status == "fail"
    assert ":sub" in check.detail


def test_missing_role_returns_fail_with_admin_remediation():
    from botocore.exceptions import ClientError

    iam = MagicMock()
    iam.get_role.side_effect = ClientError(
        {"Error": {"Code": "NoSuchEntity", "Message": "x"}}, "GetRole",
    )
    verifier = IrsaMappingVerifier(iam_client=iam, sts_client=MagicMock())
    spec = IrsaRoleSpec(
        name="foo", label="foo",
        role_name="missing-role", namespace="ns", service_account="sa",
        admin_managed_remediation="custom-hint",
    )
    check = verifier.verify_role(spec, "oidc/id/X")
    assert check.status == "fail"
    assert "custom-hint" in (check.remediation or "")
