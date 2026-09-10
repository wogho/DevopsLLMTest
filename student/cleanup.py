#!/usr/bin/env python3
"""
실습 환경을 전부 지웁니다. 강의가 끝나면 반드시 실행하세요.

    python cleanup.py            무엇이 지워지는지 보여주고 확인
    python cleanup.py --yes      확인 없이 바로

★ EKS 클러스터는 켜두면 계속 요금이 나갑니다. 꼭 지우세요.

지우는 순서가 중요합니다.
  1. LoadBalancer 서비스 (Gitea / ArgoCD)  ← 먼저 지워야 ELB 가 정리됩니다
  2. CloudFormation 스택                   ← 나머지 전부
ELB 가 남아 있으면 VPC 삭제가 실패합니다.
"""

import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

MARK = "# --- 8< --- AUTO GENERATED BELOW --- 8< ---"
STACK = os.environ.get("STACK", "kdt-devops-lab")
OK, NG = "\033[92m✅\033[0m", "\033[91m❌\033[0m"


def main():
    import boto3
    from dotenv import load_dotenv

    env = HERE / ".env"
    if not env.exists():
        print(f"{NG} .env 가 없습니다.")
        return 1
    head = env.read_text(encoding="utf-8").split(MARK)[0]
    load_dotenv(env, override=True)

    session = boto3.Session(
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_DEFAULT_REGION"),
    )
    try:
        me = session.client("sts").get_caller_identity()
    except Exception as e:  # noqa: BLE001
        print(f"{NG} AWS 연결 실패: {str(e)[:150]}")
        return 1

    print(f"\n▶ 삭제 대상   계정 {me['Account']}")
    print(f"  · EKS 클러스터와 그 안의 모든 워크로드")
    print(f"  · LoadBalancer 2개 (ArgoCD · Git 서버)")
    print(f"  · VPC · 서브넷 · IGW")
    print(f"  · SNS 토픽 · CodeBuild 프로젝트 · IAM 역할")
    print(f"  · CloudFormation 스택 {STACK}")

    if "--yes" not in sys.argv:
        if input("\n정말 삭제할까요? [y/N] ").strip().lower() != "y":
            print("취소했습니다.\n")
            return 0

    # ── 1) LoadBalancer 서비스 먼저 ────────────────────────────────────
    if os.getenv("CLUSTER_NAME"):
        print("\n▶ LoadBalancer 정리")
        try:
            from k8s import Cluster

            c = Cluster()
            for ns, name in (("argocd", "argocd-server"), ("git", "gitea-lb"),
                             ("git", "gitlab-nginx-ingress-controller")):
                try:
                    code = c.delete(f"/api/v1/namespaces/{ns}/services/{name}")
                    if code != 404:
                        print(f"{OK} {ns}/{name} 삭제")
                except Exception:  # noqa: BLE001
                    pass
            print("  ELB 가 실제로 사라질 때까지 60초 기다립니다")
            time.sleep(60)
        except Exception as e:  # noqa: BLE001
            print(f"  (클러스터에 접근하지 못했습니다: {str(e)[:100]})")
            print("  스택 삭제만 진행합니다.")

    # ── 2) 스택 삭제 ───────────────────────────────────────────────────
    print(f"\n▶ 스택 삭제  {STACK}")
    cf = session.client("cloudformation")
    try:
        cf.describe_stacks(StackName=STACK)
    except Exception:  # noqa: BLE001
        print("  스택이 이미 없습니다.")
    else:
        cf.delete_stack(StackName=STACK)
        print("  삭제 중입니다. EKS 라 15분 정도 걸립니다.")
        try:
            cf.get_waiter("stack_delete_complete").wait(
                StackName=STACK, WaiterConfig={"Delay": 20, "MaxAttempts": 90}
            )
            print(f"{OK} 스택 삭제 완료")
        except Exception:  # noqa: BLE001
            print(f"{NG} 삭제가 끝나지 않았습니다.")
            print("   대개 ELB 나 ENI 가 남아서입니다.")
            print("   AWS 콘솔 → CloudFormation → 이벤트 탭에서 어떤 리소스인지 확인하고,")
            print("   EC2 → 로드밸런서 에서 수동 삭제한 뒤 다시 실행하세요.")
            return 1

    env.write_text(head.rstrip() + "\n" + MARK + "\n", encoding="utf-8")
    print(f"{OK} .env 자동 생성 구간 비움 (액세스 키는 남아 있습니다)")
    print("\n정리가 끝났습니다. 지속 비용은 없습니다.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
