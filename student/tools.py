"""
에이전트가 사용할 도구 6개.  **전부 진짜 API 를 칩니다.**

    get_recent_changes    → Git 서버 REST API
    get_application       → Kubernetes API (ArgoCD Application CRD)
    list_pods             → Kubernetes API
    get_pod_logs          → Kubernetes API (현재 + 직전 컨테이너)
    get_events            → Kubernetes API
    send_report           → SNS  ← 쓰기
    rollback_last_change  → Git 커밋 되돌리기  ← 쓰기 · 실제 복구

이 파일은 완성본입니다. 실습에서 수정할 필요 없습니다.
다만 **한 번은 읽어보세요.** description 을 어떻게 쓰느냐가 판단 품질을 좌우합니다.

사내로 옮길 때 바뀌는 것:
  · Kubernetes  → 사내 클러스터 엔드포인트 (k8s.Cluster 의 인증만 교체)
  · Git         → 사내 GitLab 주소와 토큰
  · SNS         → Slack Webhook
  루프와 도구 스키마는 그대로입니다.
"""

import json
import os

import boto3
from dotenv import load_dotenv

import app_manifests as M
import gitsrv
from k8s import Cluster

load_dotenv()

STUDENT = os.getenv("STUDENT_NAME", "anonymous")
NAMESPACE = os.getenv("APP_NAMESPACE", M.NAMESPACE)
APP = os.getenv("APP_NAME", M.APP)
TOPIC_ARN = os.getenv("ALERT_TOPIC_ARN", "")

_cluster = None
_git = None


def cluster():
    global _cluster
    if _cluster is None:
        _cluster = Cluster()
    return _cluster


def git():
    global _git
    if _git is None:
        _git = gitsrv.from_env()
    return _git


# ===========================================================================
# 도구 스키마
# ===========================================================================
TOOL_SPECS = [
    {
        "toolSpec": {
            "name": "get_recent_changes",
            "description": (
                "배포 매니페스트 저장소의 최근 커밋을 최신순으로 반환합니다. "
                "배포 이상을 조사할 때 가장 먼저 호출하세요. "
                "'방금 무엇이 바뀌었는가'를 알아야 나머지 증상을 해석할 수 있습니다. "
                "커밋 메시지에 변경 의도가 적혀 있지만, 의도와 실제 변경이 다를 수 있으니 "
                "클러스터 상태와 반드시 대조하세요."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "가져올 커밋 수. 기본 5"}
                    },
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "get_application",
            "description": (
                "ArgoCD Application 의 동기화 상태(sync), 헬스 상태(health), "
                "마지막 동기화 리비전, 배포된 리소스 목록을 반환합니다. "
                "'지금 클러스터가 어떤 상태인가'를 파악할 때 사용하세요. "
                "health 가 Degraded 나 Progressing 이면 pod 단위로 더 파고들어야 합니다. "
                "Healthy 이고 Synced 이면 더 조사하지 말고 이상 없음으로 보고하세요."
            ),
            "inputSchema": {"json": {"type": "object", "properties": {}}},
        }
    },
    {
        "toolSpec": {
            "name": "list_pods",
            "description": (
                "네임스페이스의 pod 목록과 각 pod 의 phase, ready 여부, 재시작 횟수, "
                "현재 상태 사유, 직전 컨테이너의 종료 사유와 exit code 를 반환합니다. "
                "어느 pod 가 문제인지 특정한 뒤 그 pod 의 로그와 이벤트를 봐야 합니다. "
                "로그를 조회하기 전에 반드시 이 도구로 정확한 pod 이름을 먼저 확인하세요. "
                "직전 종료 사유(OOMKilled 등)가 여기 나오는 경우가 많으니 놓치지 마세요."
            ),
            "inputSchema": {"json": {"type": "object", "properties": {}}},
        }
    },
    {
        "toolSpec": {
            "name": "get_pod_logs",
            "description": (
                "특정 pod 의 최근 로그를 반환합니다. "
                "previous=true 로 부르면 재시작 직전 컨테이너의 로그를 봅니다. "
                "CrashLoopBackOff 인 pod 는 현재 로그가 비어 있을 수 있으므로 "
                "previous=true 로도 한 번 확인하세요. "
                "이미지를 못 받아오는 pod 는 로그 자체가 없으니 대신 get_events 를 쓰세요. "
                "pod_name 은 list_pods 결과에서 가져온 정확한 이름이어야 합니다."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "pod_name": {"type": "string", "description": "정확한 pod 이름"},
                        "previous": {"type": "boolean", "description": "직전 컨테이너 로그 여부"},
                        "tail_lines": {"type": "integer", "description": "가져올 줄 수. 기본 60"},
                    },
                    "required": ["pod_name"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "get_events",
            "description": (
                "네임스페이스의 최근 쿠버네티스 이벤트를 최신순으로 반환합니다. "
                "이미지 pull 실패, probe 실패, 스케줄링 실패처럼 "
                "**애플리케이션 로그에는 절대 안 남는 원인**이 여기 있습니다. "
                "로그가 비어 있거나 정상인데 pod 가 Ready 가 아니면 반드시 이 도구를 쓰세요."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "가져올 이벤트 수. 기본 25"}
                    },
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "send_report",
            "description": (
                "진단 결과를 운영 채널(SNS)로 보고합니다. "
                "조사가 끝난 뒤 **마지막에 딱 한 번만** 호출하세요. "
                "사람이 읽고 바로 행동할 수 있는 형태로 작성해야 합니다."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "subject": {"type": "string", "description": "한 줄 제목. 60자 이내"},
                        "text": {"type": "string", "description": "진단 리포트 본문"},
                    },
                    "required": ["subject", "text"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "rollback_last_change",
            "description": (
                "직전 커밋으로 인해 장애가 생겼다고 확신할 때, 매니페스트를 이전 상태로 "
                "되돌리는 커밋을 만듭니다. ArgoCD 가 자동으로 동기화해 실제로 복구됩니다. "
                "**되돌리기 전에 반드시 원인을 특정하고 보고까지 마치세요.** "
                "원인이 불확실하면 이 도구를 쓰지 말고 사람에게 판단을 넘기세요. "
                "이 도구는 실제 운영 상태를 바꿉니다."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "reason": {
                            "type": "string",
                            "description": "되돌리는 이유. 커밋 메시지에 들어갑니다.",
                        }
                    },
                    "required": ["reason"],
                }
            },
        }
    },
]


# ===========================================================================
# 도구 구현
# ===========================================================================
# LLM 은 이 함수들을 직접 실행하지 않습니다.
# "이 도구를 이 인자로 불러줘"라고 요청할 뿐이고, 실행 여부는 우리 코드가 정합니다.


def get_recent_changes(limit: int = 5):
    return {"commits": git().recent_commits(limit)}


def get_application():
    app = cluster().argo_app(APP)
    st = app.get("status", {})
    resources = [
        {
            "kind": r.get("kind"),
            "name": r.get("name"),
            "status": r.get("status"),
            "health": (r.get("health") or {}).get("status"),
        }
        for r in st.get("resources", [])
    ]
    return {
        "name": APP,
        "sync_status": st.get("sync", {}).get("status"),
        "revision": (st.get("sync", {}).get("revision") or "")[:8],
        "health_status": st.get("health", {}).get("status"),
        "health_message": st.get("health", {}).get("message", ""),
        "operation_phase": st.get("operationState", {}).get("phase"),
        "resources": resources,
    }


def list_pods():
    out = []
    for p in cluster().pods(NAMESPACE):
        st = p.get("status", {})
        for cs in st.get("containerStatuses", []) or [{}]:
            state = cs.get("state", {})
            last = cs.get("lastState", {}).get("terminated", {})
            reason = ""
            for kind in ("waiting", "terminated"):
                if kind in state:
                    reason = state[kind].get("reason", "")
            out.append(
                {
                    "name": p["metadata"]["name"],
                    "phase": st.get("phase"),
                    "ready": cs.get("ready"),
                    "restarts": cs.get("restartCount", 0),
                    "state": reason or "running",
                    "last_terminated_reason": last.get("reason", ""),
                    "last_exit_code": last.get("exitCode"),
                }
            )
    return {"pods": out}


def get_pod_logs(pod_name: str, previous: bool = False, tail_lines: int = 60):
    try:
        text = cluster().pod_logs(NAMESPACE, pod_name, tail=tail_lines, previous=previous)
    except Exception as exc:  # noqa: BLE001
        return {
            "pod": pod_name,
            "log": "",
            "note": (
                f"로그를 가져오지 못했습니다: {exc}. "
                "컨테이너가 아직 시작되지 않았을 수 있습니다. get_events 를 확인하세요."
            ),
        }
    if not text.strip():
        return {
            "pod": pod_name,
            "log": "",
            "note": "로그가 비어 있습니다. get_events 로 컨테이너 시작 실패 여부를 확인하세요.",
        }
    return {"pod": pod_name, "previous": previous, "log": text[-6000:]}


def get_events(limit: int = 25):
    out = []
    for e in cluster().events(NAMESPACE, limit=limit * 2)[:limit]:
        out.append(
            {
                "type": e.get("type"),
                "reason": e.get("reason"),
                "object": f"{e.get('involvedObject', {}).get('kind')}/"
                          f"{e.get('involvedObject', {}).get('name')}",
                "message": (e.get("message") or "")[:300],
                "count": e.get("count", 1),
            }
        )
    return {"events": out}


def send_report(subject: str, text: str):
    if not TOPIC_ARN:
        return {"error": "ALERT_TOPIC_ARN 이 설정되지 않았습니다."}
    boto3.Session(
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_DEFAULT_REGION"),
    ).client("sns").publish(
        TopicArn=TOPIC_ARN,
        Subject=f"[{STUDENT}] {subject}"[:100],
        Message=text,
    )
    return {"ok": True, "message": "운영 채널에 보고했습니다."}


def rollback_last_change(reason: str):
    """정상 매니페스트로 되돌리는 커밋을 만듭니다. ArgoCD 가 실제로 복구합니다."""
    good = M.SCENARIOS["healthy"]["manifest"]()
    sha = git().put_file(
        M.MANIFEST_PATH,
        good,
        f"revert: 자동 복구 — {reason}",
    )
    return {
        "ok": True,
        "commit": sha,
        "message": "매니페스트를 정상 상태로 되돌렸습니다. "
                   "ArgoCD 가 30초 안에 동기화합니다. 복구 확인은 사람이 해주세요.",
    }


# ===========================================================================
REGISTRY = {
    "get_recent_changes": get_recent_changes,
    "get_application": get_application,
    "list_pods": list_pods,
    "get_pod_logs": get_pod_logs,
    "get_events": get_events,
    "send_report": send_report,
    "rollback_last_change": rollback_last_change,
}

# 부수효과가 있는 도구. 사람 승인 없이는 실행하지 않습니다.
WRITE_TOOLS = {"send_report", "rollback_last_change"}


def run_tool(name: str, arguments: dict):
    """도구를 실행하고 결과를 돌려줍니다.

    예외를 밖으로 던지지 않는 것이 중요합니다.
    도구가 실패해도 그 사실을 LLM 에게 알려주면 다른 방법을 시도합니다.
    """
    fn = REGISTRY.get(name)
    if fn is None:
        return {"error": f"알 수 없는 도구입니다: {name}"}
    try:
        return fn(**(arguments or {}))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
