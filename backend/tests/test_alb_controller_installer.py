"""
Tests for AlbControllerInstaller.

Mocks the kubernetes apps_v1 client + boto3 clients so the unit tests
do not require a cluster or `helm` on PATH. Verifies:
  - detect() returns installed=True when the deployment is ready.
  - ensure() in preprovisioned mode returns fail with remediation when
    missing.
  - ensure() in managed mode without `helm` on PATH returns fail with
    a helm install hint (no exception).
"""
from unittest.mock import MagicMock, patch

import pytest

from app.services.alb_controller_installer import AlbControllerInstaller


def _installed_apps_v1():
    apps = MagicMock()
    dep = MagicMock()
    dep.status.ready_replicas = 2
    dep.spec.replicas = 2
    container = MagicMock()
    container.name = "aws-load-balancer-controller"
    container.image = "602401143452.dkr.ecr.us-west-2.amazonaws.com/amazon/aws-load-balancer-controller:v2.7.2"
    dep.spec.template.spec.containers = [container]
    apps.read_namespaced_deployment.return_value = dep
    return apps


def test_detect_returns_installed_when_deployment_ready():
    installer = AlbControllerInstaller(
        eks_client=MagicMock(), iam_client=MagicMock(), sts_client=MagicMock(),
        region="us-west-2", apps_v1=_installed_apps_v1(),
    )
    det = installer.detect()
    assert det["installed"] is True
    assert det["ready_replicas"] == 2
    assert "v2.7.2" in det["image"]


def test_ensure_preprovisioned_missing_returns_fail_with_remediation():
    from kubernetes.client.rest import ApiException

    apps = MagicMock()
    apps.read_namespaced_deployment.side_effect = ApiException(status=404)
    installer = AlbControllerInstaller(
        eks_client=MagicMock(), iam_client=MagicMock(), sts_client=MagicMock(),
        region="us-west-2", apps_v1=apps,
    )
    check = installer.ensure(
        cluster_name="c", oidc_provider_id="oidc.../id/X", iam_mode="preprovisioned",
    )
    assert check.status == "fail"
    assert "admin" in (check.detail or "").lower() or "admin" in (check.remediation or "").lower()


def test_ensure_managed_without_helm_returns_helm_remediation():
    from kubernetes.client.rest import ApiException

    apps = MagicMock()
    apps.read_namespaced_deployment.side_effect = ApiException(status=404)
    installer = AlbControllerInstaller(
        eks_client=MagicMock(), iam_client=MagicMock(), sts_client=MagicMock(),
        region="us-west-2", apps_v1=apps,
    )
    with patch("app.services.alb_controller_installer.shutil.which", return_value=None):
        check = installer.ensure(
            cluster_name="c", oidc_provider_id="oidc.../id/X", iam_mode="managed",
        )
    assert check.status == "fail"
    assert "helm" in (check.remediation or "").lower()
