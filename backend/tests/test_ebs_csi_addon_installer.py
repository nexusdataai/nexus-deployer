"""Tests for EbsCsiAddonInstaller."""
from unittest.mock import MagicMock

import pytest

from app.services.ebs_csi_addon_installer import (
    EBS_ADDON_NAME, EbsCsiAddonInstaller,
)


def _api_404():
    from botocore.exceptions import ClientError
    return ClientError({"Error": {"Code": "ResourceNotFoundException", "Message": "x"}}, "DescribeAddon")


def test_detect_returns_installed_for_active_addon():
    eks = MagicMock()
    eks.describe_addon.return_value = {"addon": {"status": "ACTIVE", "addonVersion": "v1.30.0"}}
    inst = EbsCsiAddonInstaller(eks_client=eks, iam_client=MagicMock(), sts_client=MagicMock(), region="us-east-1")
    det = inst.detect("c")
    assert det["installed"] is True
    assert det["status"] == "ACTIVE"


def test_detect_returns_not_installed_on_404():
    eks = MagicMock()
    eks.describe_addon.side_effect = _api_404()
    inst = EbsCsiAddonInstaller(eks_client=eks, iam_client=MagicMock(), sts_client=MagicMock(), region="us-east-1")
    det = inst.detect("c")
    assert det["installed"] is False


def test_ensure_preprovisioned_missing_returns_fail():
    eks = MagicMock()
    eks.describe_addon.side_effect = _api_404()
    inst = EbsCsiAddonInstaller(eks_client=eks, iam_client=MagicMock(), sts_client=MagicMock(), region="us-east-1")
    check = inst.ensure(cluster_name="c", oidc_provider_id="oidc/id/X", iam_mode="preprovisioned")
    assert check.status == "fail"
    assert "admin" in (check.remediation or "").lower()


def test_ensure_managed_creates_role_then_addon():
    from botocore.exceptions import ClientError

    eks = MagicMock()
    # First describe returns 404, after create_addon returns ACTIVE
    eks.describe_addon.side_effect = [
        _api_404(),
        {"addon": {"status": "ACTIVE", "addonVersion": "v1.30.0"}},
    ]
    iam = MagicMock()
    iam.get_role.side_effect = ClientError(
        {"Error": {"Code": "NoSuchEntity", "Message": "x"}}, "GetRole"
    )
    sts = MagicMock()
    sts.get_caller_identity.return_value = {"Account": "111122223333"}

    inst = EbsCsiAddonInstaller(eks_client=eks, iam_client=iam, sts_client=sts, region="us-east-1")
    check = inst.ensure(
        cluster_name="c",
        oidc_provider_id="oidc.eks.us-east-1.amazonaws.com/id/X",
        iam_mode="managed",
    )
    assert check.status == "pass"
    iam.create_role.assert_called_once()
    eks.create_addon.assert_called_once()


def test_ensure_managed_no_oidc_returns_fail():
    eks = MagicMock()
    eks.describe_addon.side_effect = _api_404()
    inst = EbsCsiAddonInstaller(eks_client=eks, iam_client=MagicMock(), sts_client=MagicMock(), region="us-east-1")
    check = inst.ensure(cluster_name="c", oidc_provider_id=None, iam_mode="managed")
    assert check.status == "fail"
    assert "OIDC" in check.detail or "oidc" in (check.remediation or "").lower()
