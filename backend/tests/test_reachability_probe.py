"""Tests for ReachabilityProbe (pod spawn + log parsing + cleanup)."""
import json
from unittest.mock import MagicMock, AsyncMock

import pytest

from app.services.reachability_probe import ReachabilityProbe


def _terminal_pod(phase: str = "Succeeded"):
    pod = MagicMock()
    pod.status.phase = phase
    return pod


@pytest.mark.asyncio
async def test_run_parses_per_service_rows_and_iam_block(monkeypatch):
    core_v1 = MagicMock()
    core_v1.create_namespaced_pod.return_value = MagicMock()
    core_v1.read_namespaced_pod.return_value = _terminal_pod("Succeeded")
    sample = "\n".join([
        json.dumps({"service": "sts", "host": "sts.us-east-1.amazonaws.com",
                    "ip": "10.0.0.1", "route": "VPCE", "tls_status": "OK", "detail": ""}),
        json.dumps({"service": "s3", "host": "s3.us-east-1.amazonaws.com",
                    "ip": "10.0.0.2", "route": "VPCE", "tls_status": "OK", "detail": ""}),
        json.dumps({"__iam__": True, "arn": "arn:aws:iam::111:role/x", "account": "111", "region": "us-east-1"}),
    ])
    core_v1.read_namespaced_pod_log.return_value = sample
    probe = ReachabilityProbe(core_v1=core_v1, region="us-east-1")
    report = await probe.run(namespace="myns", capability_name="cp", environment="test")
    assert report.overall == "pass"
    assert len(report.rows) == 2
    assert report.rows[0].service == "sts"
    assert report.iam_results["account"] == "111"
    core_v1.delete_namespaced_pod.assert_called()


@pytest.mark.asyncio
async def test_run_dns_fail_yields_fail_overall():
    core_v1 = MagicMock()
    core_v1.create_namespaced_pod.return_value = MagicMock()
    core_v1.read_namespaced_pod.return_value = _terminal_pod("Failed")
    core_v1.read_namespaced_pod_log.return_value = json.dumps({
        "service": "s3", "host": "x", "ip": None, "route": "DNS_FAIL",
        "tls_status": "", "detail": "name resolution failed",
    })
    probe = ReachabilityProbe(core_v1=core_v1, region="us-east-1")
    report = await probe.run(namespace="myns", capability_name="cp", environment="test")
    assert report.overall == "fail"


@pytest.mark.asyncio
async def test_run_handles_pod_create_failure_gracefully():
    from kubernetes.client.rest import ApiException
    core_v1 = MagicMock()
    core_v1.create_namespaced_pod.side_effect = ApiException(status=403, reason="Forbidden")
    probe = ReachabilityProbe(core_v1=core_v1, region="us-east-1")
    report = await probe.run(namespace="myns", capability_name="cp", environment="test")
    assert report.overall == "fail"
    assert "create_namespaced_pod failed" in report.iam_results.get("error", "")
