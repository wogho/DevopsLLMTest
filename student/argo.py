"""
ArgoCD 를 Kubernetes API 로 직접 제어합니다. argocd CLI 를 설치하지 않아도 됩니다.

ArgoCD 는 기본적으로 3분마다 Git 을 확인합니다. 실습에서는 너무 기니까
커밋 직후 refresh 를 강제로 걸어 즉시 감지하게 만듭니다.
"""

import json
import os
import time

APP_PATH = "/apis/argoproj.io/v1alpha1/namespaces/argocd/applications/{name}"


def app_name():
    return os.getenv("APP_NAME", "kdt-dev-api")


def get(cluster, name=None):
    return cluster.get(APP_PATH.format(name=name or app_name()))


def sync_policy(cluster, name=None):
    return get(cluster, name).get("spec", {}).get("syncPolicy") or {}


def ensure_auto_sync(cluster, name=None):
    """자동 동기화가 꺼져 있으면 켭니다. 켜져 있으면 아무것도 안 합니다."""
    pol = sync_policy(cluster, name)
    if pol.get("automated"):
        return False
    cluster.patch(
        APP_PATH.format(name=name or app_name()),
        json.dumps(
            {
                "spec": {
                    "syncPolicy": {
                        "automated": {"prune": True, "selfHeal": True},
                        "syncOptions": ["CreateNamespace=true"],
                    }
                }
            }
        ),
    )
    return True


def refresh(cluster, name=None, hard=False):
    """Git 을 지금 바로 다시 보게 만듭니다."""
    cluster.patch(
        APP_PATH.format(name=name or app_name()),
        json.dumps(
            {"metadata": {"annotations": {"argocd.argoproj.io/refresh": "hard" if hard else "normal"}}}
        ),
    )


def sync_now(cluster, name=None, revision="HEAD"):
    """자동 동기화를 기다리지 않고 즉시 동기화를 지시합니다."""
    cluster.patch(
        APP_PATH.format(name=name or app_name()),
        json.dumps(
            {
                "operation": {
                    "initiatedBy": {"username": "lab"},
                    "sync": {"revision": revision, "prune": True},
                }
            }
        ),
    )


def status(cluster, name=None):
    st = get(cluster, name).get("status", {})
    op = st.get("operationState", {}) or {}
    conds = st.get("conditions", []) or []
    return {
        "sync": st.get("sync", {}).get("status"),
        "health": st.get("health", {}).get("status"),
        "revision": (st.get("sync", {}).get("revision") or "")[:8],
        "message": st.get("health", {}).get("message", ""),
        "phase": op.get("phase"),
        # ArgoCD 는 동기화가 실패해도 sync=OutOfSync 로만 보입니다.
        # 왜 실패했는지는 여기 들어 있습니다. 이걸 안 보면 원인을 영원히 못 찾습니다.
        "operation_message": op.get("message", ""),
        "conditions": [
            f"{c.get('type')}: {c.get('message','')[:200]}" for c in conds
        ],
    }


def sync_failed(st):
    return st.get("phase") in ("Failed", "Error") or bool(st.get("conditions"))
