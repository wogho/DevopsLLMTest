#!/usr/bin/env python3
"""
실습 환경 점검.

    python check_env.py

검사 순서가 곧 준비 순서입니다. 위에서부터 하나씩 해결하세요.
❌ 가 있으면 화면을 캡처해서 강사에게 보내주세요.
"""

import os
import platform
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

PASS, FAIL, WARN, SKIP = "\033[92m✅\033[0m", "\033[91m❌\033[0m", "\033[93m⚠️ \033[0m", "⏭ "
results = []

AFTER_DEPLOY = ["CLUSTER_NAME", "APP_NAMESPACE", "APP_NAME", "ALERT_TOPIC_ARN", "GIT_BASE_URL"]


def check(title, blocking=False):
    def wrap(fn):
        results.append((title, fn, blocking))
        return fn

    return wrap


def say(mark, title, detail=""):
    print(f"{mark} {title}")
    for line in str(detail).splitlines():
        if line.strip():
            print(f"      {line}")


# ── 1 ──────────────────────────────────────────────────────────────────────
@check("Python 3.9 이상")
def _python():
    if sys.version_info < (3, 9):
        return False, f"현재 {platform.python_version()}. 3.9 이상이 필요합니다."
    return True, f"{platform.python_version()}  ({sys.executable})"


@check("필수 패키지", blocking=True)
def _packages():
    missing = []
    for mod, name in [("boto3", "boto3"), ("requests", "requests"), ("dotenv", "python-dotenv")]:
        try:
            __import__(mod)
        except ImportError:
            missing.append(name)
    if missing:
        return False, (
            f"누락: {', '.join(missing)}\n"
            "해결:  pip install -r requirements.txt\n"
            "사내망에서 막히면:  pip install -r requirements.txt -i <사내 PyPI>"
        )
    import boto3

    return True, f"boto3 {boto3.__version__}"


@check(".env 파일", blocking=True)
def _dotenv():
    if not (HERE / ".env").exists():
        return False, (
            ".env 가 없습니다.\n"
            "  cp .env.example .env      (Windows: copy .env.example .env)\n"
            "그리고 위쪽 값들을 채워주세요."
        )
    from dotenv import load_dotenv

    load_dotenv(HERE / ".env", override=True)
    manual = ["STUDENT_NAME", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION"]
    missing = [k for k in manual if not os.getenv(k)]
    if missing:
        return False, f"아직 비어 있는 값: {', '.join(missing)}"
    import re

    name = os.getenv("STUDENT_NAME", "")
    if not re.fullmatch(r"[a-z0-9-]{2,20}", name):
        return False, f"STUDENT_NAME 은 소문자/숫자/하이픈 2~20자여야 합니다: '{name}'"
    return True, f"STUDENT_NAME={name}  ·  region={os.getenv('AWS_DEFAULT_REGION')}"


@check("AWS 자격증명", blocking=True)
def _aws():
    import boto3
    import botocore.exceptions as be

    os.environ.pop("AWS_PROFILE", None)
    os.environ["AWS_REGION"] = os.getenv("AWS_DEFAULT_REGION", "ap-northeast-2")
    try:
        me = boto3.client("sts").get_caller_identity()
    except be.ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("InvalidClientTokenId", "SignatureDoesNotMatch", "UnrecognizedClientException"):
            return False, ".env 의 액세스 키를 다시 확인해주세요. (앞뒤 공백·따옴표 주의)"
        return False, f"인증 실패: {code}"
    except Exception as e:  # noqa: BLE001
        return False, (
            f"AWS 연결 오류: {type(e).__name__}: {str(e)[:160]}\n"
            "사내 프록시:  export HTTPS_PROXY=http://<프록시>:<포트>"
        )
    return True, f"계정 {me['Account']}\n{me['Arn']}"


@check("실습 인프라 배포", blocking=True)
def _stack():
    missing = [k for k in AFTER_DEPLOY if not os.getenv(k)]
    if missing:
        return False, (
            "아직 인프라가 만들어지지 않았습니다.\n"
            "  python deploy_lab.py\n"
            "25~35분 걸립니다. 끝나면 .env 아래쪽이 자동으로 채워집니다."
        )
    return True, f"클러스터 {os.getenv('CLUSTER_NAME')}"


# ── 2 ──────────────────────────────────────────────────────────────────────
@check("Bedrock 모델 호출")
def _bedrock():
    import boto3
    from botocore.exceptions import ClientError

    region = os.getenv("AWS_DEFAULT_REGION", "ap-northeast-2")
    model_id = os.getenv("BEDROCK_MODEL_ID", "")
    rt = boto3.client("bedrock-runtime", region_name=region)

    def call(mid):
        rt.converse(
            modelId=mid,
            messages=[{"role": "user", "content": [{"text": "ping"}]}],
            inferenceConfig={"maxTokens": 8},
        )

    def diagnose(e):
        msg = e.response["Error"]["Message"]
        if any(w in msg.lower() for w in ("marketplace", "subscription", "not authorized", "entitlement")):
            return (
                "이 계정에서 Anthropic 모델이 아직 활성화되지 않았습니다.\n"
                "계정마다 최초 1회 사용 목적 양식이 필요합니다. 강사에게 알려주세요.\n"
                f"원문: {msg[:180]}"
            )
        return f"{e.response['Error']['Code']}: {msg[:180]}"

    first = "BEDROCK_MODEL_ID 가 비어 있습니다."
    if model_id:
        try:
            call(model_id)
            return True, f"{model_id}  호출 성공"
        except ClientError as e:
            if e.response["Error"]["Code"] == "ThrottlingException":
                return True, f"{model_id}  (일시적 쓰로틀링 — 정상)"
            first = diagnose(e)
            if e.response["Error"]["Code"] not in ("ValidationException", "AccessDeniedException"):
                return False, first

    try:
        opts = [
            p["inferenceProfileId"]
            for p in boto3.client("bedrock", region_name=region)
            .list_inference_profiles()["inferenceProfileSummaries"]
            if "haiku" in p["inferenceProfileId"] and "claude" in p["inferenceProfileId"]
        ]
    except ClientError:
        opts = []
    for mid in opts:
        try:
            call(mid)
            return True, f"{mid} 호출 성공\n{WARN}.env 의 BEDROCK_MODEL_ID 를 위 값으로 바꿔주세요."
        except ClientError:
            continue
    return False, f"{first}\n이 리전의 대체 후보: {opts or '없음'}"


@check("Kubernetes API 접근", blocking=True)
def _k8s():
    from k8s import Cluster

    try:
        c = Cluster()
        ver = c.get("/version")
        nodes = c.get("/api/v1/nodes")["items"]
    except Exception as e:  # noqa: BLE001
        return False, (
            f"클러스터에 접근하지 못했습니다: {type(e).__name__}: {str(e)[:200]}\n"
            "python deploy_lab.py 를 다시 실행해보세요."
        )
    return True, (
        f"Kubernetes {ver.get('gitVersion')}  ·  노드 {len(nodes)}개\n"
        + "\n".join(
            f"{n['metadata']['name']}  {n['status']['nodeInfo']['osImage']}" for n in nodes[:3]
        )
    )


@check("ArgoCD 와 앱 상태")
def _argo():
    import tools

    try:
        app = tools.get_application()
    except Exception as e:  # noqa: BLE001
        return False, f"ArgoCD Application 을 읽지 못했습니다: {str(e)[:180]}"

    pods = tools.list_pods()["pods"]
    ready = sum(1 for p in pods if p["ready"])
    detail = (
        f"sync={app['sync_status']}  health={app['health_status']}  rev={app['revision']}\n"
        f"pod {ready}/{len(pods)} Ready"
    )
    if app["health_status"] != "Healthy":
        return True, detail + f"\n{WARN}지금 정상 상태가 아닙니다. 장애 시나리오가 걸려 있을 수 있습니다."
    return True, detail


@check("Git 서버 연결")
def _git():
    import gitsrv

    try:
        c = gitsrv.from_env()
        commits = c.recent_commits(1)
    except Exception as e:  # noqa: BLE001
        return False, f"Git 서버에 연결하지 못했습니다: {str(e)[:180]}"
    latest = commits[0]["message"] if commits else "(커밋 없음)"
    return True, f"{os.getenv('GIT_BASE_URL')}\n최근 커밋: {latest[:60]}"


@check("알림 채널 (SNS)")
def _sns():
    import boto3

    arn = os.getenv("ALERT_TOPIC_ARN", "")
    if not arn:
        return False, "ALERT_TOPIC_ARN 이 비어 있습니다."
    try:
        subs = boto3.client("sns").list_subscriptions_by_topic(TopicArn=arn)["Subscriptions"]
    except Exception as e:  # noqa: BLE001
        return False, f"SNS 토픽을 읽지 못했습니다: {str(e)[:150]}"
    confirmed = [s for s in subs if s["SubscriptionArn"].startswith("arn:")]
    if not subs:
        return True, (
            f"{WARN}구독자가 없습니다. 리포트는 SNS 에 발행만 되고 아무도 받지 못합니다.\n"
            "재배포 없이 지금 추가할 수 있습니다:\n"
            "  python alerts.py you@company.com"
        )
    if not confirmed:
        return True, (
            f"{WARN}구독 확인이 아직입니다.\n"
            "AWS Notification - Subscription Confirmation 메일의 링크를 눌러주세요.\n"
            "확인 후:  python alerts.py --test"
        )
    return True, f"구독 {len(confirmed)}개 확인됨"


# ──────────────────────────────────────────────────────────────────────────
def main():
    print("\n실습 환경을 점검합니다\n" + "─" * 60)
    ok, halted = True, False
    for title, fn, blocking in results:
        if halted:
            say(SKIP, title, "앞 단계를 먼저 해결한 뒤 다시 실행하세요.")
            continue
        try:
            passed, detail = fn()
        except Exception:  # noqa: BLE001
            passed, detail = False, traceback.format_exc(limit=2)
        say(PASS if passed else FAIL, title, detail)
        ok = ok and passed
        if not passed and blocking:
            halted = True
    print("─" * 60)
    if ok:
        print("\n모두 통과했습니다.\n")
        print("  다음:  python status.py         지금 클러스터 상태 보기")
        print("         python break_it.py      장애 목록 보기\n")
        return 0
    print("\n❌ 항목이 있습니다. 위 안내대로 조치한 뒤 다시 실행해주세요.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
