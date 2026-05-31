"""
Authenticated Kubernetes API client builders.

Works around a regression in ``kubernetes==36.0.0`` where
``load_incluster_config()`` populates ``Configuration.api_key`` but
``Configuration.auth_settings()`` returns ``{}`` — so every outbound request
ships without an ``Authorization`` header and the API server returns 401.

We bypass the library's broken auth_settings path by reading the projected
ServiceAccount token directly and injecting it via ``set_default_header`` on
each ApiClient we hand out. Every sync K8s client constructed inside the
operator should go through ``authed_api_client()`` so this fix lands
consistently.

When the upstream library publishes a fix (likely 36.0.2+), we can simplify
to a plain ``client.ApiClient(configuration=cfg)`` and drop the manual token
read.
"""
from __future__ import annotations

import logging
from typing import Optional

from kubernetes import client, config as k8s_config

logger = logging.getLogger(__name__)

_IN_CLUSTER_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"


def authed_api_client() -> client.ApiClient:
    """Return an ``ApiClient`` with valid in-cluster auth already wired.

    Falls back to local kubeconfig when run outside a pod (dev/test). Safe
    to call repeatedly — each call constructs an isolated Configuration so
    there's no shared mutable state between callers.
    """
    cfg = client.Configuration()
    in_cluster = True
    try:
        k8s_config.load_incluster_config(client_configuration=cfg)
    except k8s_config.config_exception.ConfigException:
        in_cluster = False
        try:
            k8s_config.load_kube_config(client_configuration=cfg)
        except Exception as e:
            logger.warning(f"Neither in-cluster nor kube_config could be loaded: {e}")

    api_client = client.ApiClient(configuration=cfg)

    if in_cluster:
        try:
            with open(_IN_CLUSTER_TOKEN_PATH) as f:
                token = f.read().strip()
            api_client.set_default_header("Authorization", f"Bearer {token}")
        except Exception as e:
            logger.warning(f"Could not read in-cluster SA token: {e}")

    return api_client


def authed_custom_objects_api() -> client.CustomObjectsApi:
    """Shortcut: authenticated ``CustomObjectsApi`` for CRD reads/writes."""
    return client.CustomObjectsApi(api_client=authed_api_client())
