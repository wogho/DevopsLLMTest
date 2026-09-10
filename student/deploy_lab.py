#!/usr/bin/env python3
"""
실습 인프라 전체를 만듭니다.

    python deploy_lab.py

준비:
    cp .env.example .env      (Windows: copy .env.example .env)
    .env 위쪽 값들을 채우세요.

단계 (전체 25~35분):
    1. CloudFormation      VPC + EKS Auto Mode 클러스터        약 15분
    2. CodeBuild 부트스트랩 ArgoCD + Git 서버 설치              약 8분
    3. 리포지토리 시드      앱 매니페스트 커밋                   약 1분
    4. ArgoCD Application  앱 배포 + Healthy 대기               약 3분
    5. .env 갱신           클러스터 주소·Git 주소 자동 기록

중간에 끊겨도 다시 실행하면 이어서 진행합니다.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

ENV_FILE = HERE / ".env"
TEMPLATE = HERE.parent / "infra" / "lab-stack.yaml"
MARK = "# --- 8< --- AUTO GENERATED BELOW --- 8< ---"
STACK = os.environ.get("STACK", "kdt-devops-lab")

OK, NG, DOT = "\033[92m✅\033[0m", "\033[91m❌\033[0m", "  "


def die(msg):
    print(f"{NG} {msg}")
    sys.exit(1)


def step(n, total, title):
    print(f"\n\033[1m[{n}/{total}] {title}\033[0m")


# ---------------------------------------------------------------------------
def read_env():
    if not ENV_FILE.exists():
        die(".env 가 없습니다.  cp .env.example .env  후 값을 채워주세요.")
    head = ENV_FILE.read_text(encoding="utf-8").split(MARK)[0]
    cfg = {}
    for line in head.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip("'\"")
    return head, cfg


def write_env(head, generated):
    ENV_FILE.write_text(head.rstrip() + "\n" + MARK + "\n" + generated, encoding="utf-8")


# ---------------------------------------------------------------------------
def show_failures(cf, stack_ref):
    try:
        events = cf.describe_stack_events(StackName=stack_ref)["StackEvents"]
    except Exception:  # noqa: BLE001
        print("  실패 이벤트를 읽지 못했습니다. AWS 콘솔 CloudFormation 이벤트 탭을 확인하세요.")
        return
    # 진짜 실패만 골라냅니다. "Resource creation Initiated" 같은 진행 로그는 걸러야
    # 무엇 때문에 죽었는지가 보입니다.
    noise = ("cancelled", "resource creation initiated", "resource update initiated")
    failures = [
        e for e in events
        if "FAILED" in e.get("ResourceStatus", "")
        and e.get("ResourceStatusReason")
        and not any(n in e["ResourceStatusReason"].lower() for n in noise)
    ]
    print("\n  ── 실패 원인 ──")
    if not failures:
        print("  실패 사유가 기록된 이벤트가 없습니다.")
        print("  AWS 콘솔 → CloudFormation → 이벤트 탭을 확인해주세요.")
        return
    for e in failures[:6]:
        print(f"\n  [{e['LogicalResourceId']}]  {e.get('ResourceType','')}")
        print(f"  {e['ResourceStatusReason'][:400]}")


def deploy_stack(cf, params):
    body = TEMPLATE.read_text(encoding="utf-8")
    common = dict(
        StackName=STACK,
        TemplateBody=body,
        Parameters=[{"ParameterKey": k, "ParameterValue": v} for k, v in params.items()],
        Capabilities=["CAPABILITY_NAMED_IAM"],
    )
    bad = {"ROLLBACK_COMPLETE", "ROLLBACK_FAILED", "CREATE_FAILED", "DELETE_FAILED"}
    try:
        status = cf.describe_stacks(StackName=STACK)["Stacks"][0]["StackStatus"]
    except Exception:  # noqa: BLE001
        status = None

    if status in bad:
        print(f"{DOT}이전 스택이 {status} 입니다. 지우고 다시 만듭니다")
        print(f"{DOT}EKS 가 포함돼 있어 삭제에 10분 안팎 걸립니다")
        cf.delete_stack(StackName=STACK)
        cf.get_waiter("stack_delete_complete").wait(
            StackName=STACK, WaiterConfig={"Delay": 15, "MaxAttempts": 80}
        )
        status = None

    if status:
        try:
            cf.update_stack(**common)
            waiter = "stack_update_complete"
        except Exception as e:  # noqa: BLE001
            if "No updates are to be performed" in str(e):
                print(f"{DOT}변경 사항 없음 — 기존 클러스터를 사용합니다")
                return
            raise
    else:
        cf.create_stack(**common, OnFailure="DO_NOTHING")
        waiter = "stack_create_complete"

    print(f"{DOT}EKS 컨트롤플레인 생성에 12분 안팎이 걸립니다. 그동안 커피 한 잔 하세요.")
    started = time.time()
    try:
        cf.get_waiter(waiter).wait(
            StackName=STACK, WaiterConfig={"Delay": 20, "MaxAttempts": 90}
        )
    except Exception:  # noqa: BLE001
        show_failures(cf, STACK)
        die("스택 생성에 실패했습니다.")
    print(f"{OK} 클러스터 준비 완료 ({int(time.time()-started)//60}분 {int(time.time()-started)%60}초)")


# ---------------------------------------------------------------------------
def run_bootstrap(session, project):
    cb = session.client("codebuild")
    build_id = cb.start_build(projectName=project)["build"]["id"]
    print(f"{DOT}부트스트랩 시작: {build_id}")
    print(f"{DOT}ArgoCD 와 Git 서버를 설치합니다. 8~15분 걸립니다.")

    last_phase = None
    started = time.time()
    while True:
        time.sleep(15)
        b = cb.batch_get_builds(ids=[build_id])["builds"][0]
        phase = b.get("currentPhase")
        if phase != last_phase:
            print(f"{DOT}[{int(time.time()-started)//60}분] {phase}")
            last_phase = phase
        if b["buildStatus"] != "IN_PROGRESS":
            break

    if b["buildStatus"] != "SUCCEEDED":
        print(f"{NG} 부트스트랩 실패: {b['buildStatus']}")
        logs = b.get("logs", {})
        if logs.get("deepLink"):
            print(f"   로그: {logs['deepLink']}")
        tail_build_log(session, logs)
        die("부트스트랩에 실패했습니다. 위 로그를 확인하세요.")
    print(f"{OK} 부트스트랩 완료")


def tail_build_log(session, logs, lines=40):
    group, stream = logs.get("groupName"), logs.get("streamName")
    if not group or not stream:
        return
    try:
        ev = session.client("logs").get_log_events(
            logGroupName=group, logStreamName=stream, limit=lines, startFromHead=False
        )["events"]
        print("\n  ── 빌드 로그 끝부분 ──")
        for e in ev[-lines:]:
            print("  " + e["message"].rstrip()[:200])
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
def seed_repository(cluster, cfg, out):
    """리포지토리를 만들고 앱 매니페스트를 커밋한 뒤 ArgoCD Application 을 만듭니다."""
    import app_manifests as M
    import gitsrv

    info = cluster.configmap(out["AppNamespace"], "lab-info")
    git_host = info["git_host"]
    provider = info.get("git_provider", "gitea")

    if provider == "gitea":
        base = f"http://{git_host}:3000"
        client = gitsrv.GiteaClient(base, "labadmin", "LabAdmin!2026")
        git_env = {
            "GIT_PROVIDER": "gitea",
            "GIT_BASE_URL": base,
            "GIT_USER": "labadmin",
            "GIT_PASSWORD": "LabAdmin!2026",
        }
    else:
        base = f"http://{git_host}"
        token = os.getenv("GIT_TOKEN", "")
        client = gitsrv.GitLabClient(base, token, "root")
        git_env = {
            "GIT_PROVIDER": "gitlab",
            "GIT_BASE_URL": base,
            "GIT_USER": "root",
            "GIT_TOKEN": token,
        }

    print(f"{DOT}Git 서버: {base}")
    for attempt in range(30):
        try:
            created = client.ensure_repo()
            break
        except Exception as e:  # noqa: BLE001
            if attempt == 29:
                die(f"Git 서버에 연결하지 못했습니다: {str(e)[:160]}")
            time.sleep(10)
    print(f"{OK} 리포지토리 {'생성' if created else '확인'}: {gitsrv.REPO}")

    sha = client.put_file(
        M.MANIFEST_PATH, M.SCENARIOS["healthy"]["manifest"](), "feat: kdt-dev-api 최초 배포"
    )
    print(f"{OK} 앱 매니페스트 커밋: {sha}")

    app = M.argocd_application(client.clone_url(internal=True))
    cluster.apply(
        "/apis/argoproj.io/v1alpha1/namespaces/argocd/applications/" + M.APP,
        json.dumps(app),
    )
    print(f"{OK} ArgoCD Application 생성: {M.APP}")
    return git_env


def wait_healthy(cluster, app_name, minutes=6):
    print(f"{DOT}앱이 Healthy 가 될 때까지 기다립니다")
    for i in range(minutes * 6):
        time.sleep(10)
        try:
            st = cluster.argo_app(app_name).get("status", {})
            sync = st.get("sync", {}).get("status")
            health = st.get("health", {}).get("status")
            print(f"{DOT}[{i*10:>3}초] sync={sync} health={health}")
            if health == "Healthy" and sync == "Synced":
                print(f"{OK} 앱이 정상 배포됐습니다")
                return True
        except Exception:  # noqa: BLE001
            pass
    print(f"{NG} 아직 Healthy 가 아닙니다. python status.py 로 확인해보세요.")
    return False


# ---------------------------------------------------------------------------
def main():
    try:
        import boto3
    except ImportError:
        die("pip install -r requirements.txt 를 먼저 실행하세요.")

    head, cfg = read_env()
    need = ["STUDENT_NAME", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION"]
    missing = [k for k in need if not cfg.get(k)]
    if missing:
        die(f".env 에서 비어 있는 값: {', '.join(missing)}")
    if not re.fullmatch(r"[a-z0-9-]{2,20}", cfg["STUDENT_NAME"]):
        die(f"STUDENT_NAME 은 소문자/숫자/하이픈 2~20자여야 합니다: '{cfg['STUDENT_NAME']}'")

    os.environ.update({k: cfg[k] for k in need if k.startswith("AWS")})
    session = boto3.Session(
        aws_access_key_id=cfg["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=cfg["AWS_SECRET_ACCESS_KEY"],
        region_name=cfg["AWS_DEFAULT_REGION"],
    )

    total = 5
    step(1, total, "자격증명 확인")
    try:
        me = session.client("sts").get_caller_identity()
    except Exception as e:  # noqa: BLE001
        die(f"AWS 인증 실패: {type(e).__name__}: {str(e)[:160]}")
    print(f"{OK} 계정 {me['Account']}  ·  {cfg['AWS_DEFAULT_REGION']}")

    # 추가 관리자 ARN 은 부가 기능입니다.
    # 값이 잘못됐다고 15분짜리 스택 생성을 통째로 실패시키지 않습니다.
    from iamutil import looks_valid, normalize_principal

    extra_admin, note = normalize_principal(
        cfg.get("EXTRA_ADMIN_ARN", ""), session.client("iam")
    )
    if note:
        print(f"{DOT}{note}")
    if extra_admin and not looks_valid(extra_admin):
        print(f"{NG} EXTRA_ADMIN_ARN 이 올바른 IAM 주체 ARN 이 아닙니다: {extra_admin}")
        print(f"{DOT}이 값은 건너뜁니다. 나중에 python grant_access.py <ARN> 으로 추가하세요.")
        extra_admin = ""

    step(2, total, "인프라 생성  (VPC + EKS Auto Mode)")
    cf = session.client("cloudformation")
    deploy_stack(
        cf,
        {
            "StudentName": cfg["STUDENT_NAME"],
            "CallerArn": me["Arn"],
            "GitProvider": cfg.get("GIT_PROVIDER", "gitea"),
            "AlertEmail": cfg.get("ALERT_EMAIL", ""),
            "ExtraAdminArn": extra_admin,
        },
    )
    out = {
        o["OutputKey"]: o["OutputValue"]
        for o in cf.describe_stacks(StackName=STACK)["Stacks"][0].get("Outputs", [])
    }

    # 뒤 단계에서 실패해도 kube.py / grant_access.py 를 쓸 수 있도록 먼저 기록합니다
    write_env(
        head,
        "\n".join(
            [
                f"CLUSTER_NAME={out['ClusterName']}",
                f"CLUSTER_ENDPOINT={out['ClusterEndpoint']}",
                f"APP_NAMESPACE={out['AppNamespace']}",
                f"APP_NAME={out['AppName']}",
                f"ALERT_TOPIC_ARN={out['AlertTopicArn']}",
            ]
        )
        + "\n",
    )
    print(f"{DOT}.env 에 클러스터 정보를 먼저 기록했습니다 (kube.py 를 바로 쓸 수 있습니다)")

    step(3, total, "클러스터 부트스트랩  (ArgoCD + Git 서버)")
    run_bootstrap(session, out["BootstrapProjectName"])

    step(4, total, "리포지토리 시드 + 앱 배포")
    os.environ["CLUSTER_NAME"] = out["ClusterName"]
    from k8s import Cluster

    cluster = Cluster(out["ClusterName"], session)
    git_env = seed_repository(cluster, cfg, out)
    wait_healthy(cluster, out["AppName"])

    step(5, total, ".env 갱신")
    generated = "\n".join(
        [
            f"CLUSTER_NAME={out['ClusterName']}",
            f"CLUSTER_ENDPOINT={out['ClusterEndpoint']}",
            f"APP_NAMESPACE={out['AppNamespace']}",
            f"APP_NAME={out['AppName']}",
            f"ALERT_TOPIC_ARN={out['AlertTopicArn']}",
        ]
        + [f"{k}={v}" for k, v in git_env.items()]
    ) + "\n"
    write_env(head, generated)
    print(f"{OK} 기록 완료")
    for line in generated.strip().splitlines():
        print(f"    {line}")

    argo = cluster.service_host("argocd", "argocd-server")
    print("\n" + "═" * 62)
    print("  실습 환경이 준비됐습니다.")
    if argo:
        print(f"  ArgoCD UI :  https://{argo}   (admin / 아래 명령으로 비밀번호 확인)")
        print("               python argocd_password.py")
    print(f"  Git 서버   :  {git_env['GIT_BASE_URL']}")
    print("═" * 62)
    print("""
  kubectl 로 직접 보고 싶다면
  ─────────────────────────────────────────────────────────
  · 설치 없이 바로:      python kube.py pods -A
  · CloudShell 에서 kubectl 을 쓰려면 권한을 한 번 더 줘야 합니다.
      CloudShell:  aws sts get-caller-identity --query Arn --output text
      여기서:      python grant_access.py <그 ARN>
      CloudShell:  aws eks update-kubeconfig --name {cluster} --region {region}
                   kubectl get pods -A
    (다음 배포부터는 .env 의 EXTRA_ADMIN_ARN 에 적어두면 자동으로 들어갑니다)
""".format(cluster=out["ClusterName"], region=cfg["AWS_DEFAULT_REGION"]))
    print("\n다음:  python check_env.py\n")


if __name__ == "__main__":
    main()
