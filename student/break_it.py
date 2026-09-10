#!/usr/bin/env python3
"""
실제 장애를 일으킵니다.

    python break_it.py                목록 보기
    python break_it.py oom            이 장애를 실제로 발생시킴
    python break_it.py healthy        정상으로 되돌림
    python break_it.py oom --no-wait  커밋만 하고 바로 빠져나옴

무슨 일이 일어나는가:
    1. 앱 매니페스트를 실제로 커밋합니다          (Git 서버 API)
    2. ArgoCD 에 refresh 를 걸어 즉시 감지시킵니다 (기본 폴링은 3분이라 실습에 김)
    3. ArgoCD 가 클러스터에 적용합니다
    4. pod 가 진짜로 실패합니다 — 진짜 이벤트, 진짜 로그가 남습니다

모의가 아닙니다. kubectl get pods 로 직접 확인할 수 있습니다.
"""

import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

WAIT_SECONDS = 180


def pods_broken(cluster, min_age=45):
    """pod 가 실제로 문제 상태인지 봅니다.

    주의: 롤링 업데이트 중에는 새 pod 가 잠깐 ready=False 입니다.
    그걸 장애로 세면 배포가 정상인데도 '장애 발생'이라고 오판합니다.
    그래서 두 가지로 나눕니다.

      확정 신호  — 즉시 장애로 봅니다
          CrashLoopBackOff · ImagePullBackOff · 재시작 · OOMKilled 흔적
      약한 신호  — 45초 이상 지속돼야 장애로 봅니다
          Running 인데 Ready 가 아님  (probe 실패 시나리오가 여기 해당)
    """
    import datetime

    ns = os.getenv("APP_NAMESPACE", "kdt-dev")
    now = datetime.datetime.now(datetime.timezone.utc)

    for p in cluster.pods(ns):
        phase = p.get("status", {}).get("phase")
        started = p.get("status", {}).get("startTime")
        age = 0
        if started:
            age = (now - datetime.datetime.fromisoformat(started.replace("Z", "+00:00"))).total_seconds()

        for cs in p.get("status", {}).get("containerStatuses", []) or []:
            waiting = cs.get("state", {}).get("waiting", {}).get("reason", "")
            last = cs.get("lastState", {}).get("terminated", {})

            # 확정 신호
            if waiting in ("ImagePullBackOff", "ErrImagePull", "CrashLoopBackOff"):
                return True
            if cs.get("restartCount", 0) > 0:
                return True
            if last.get("reason") in ("OOMKilled", "Error"):
                return True

            # 약한 신호 — 충분히 오래 지속됐을 때만
            if cs.get("ready") is False and phase == "Running" and age >= min_age:
                return True
    return False


def main():
    try:
        from dotenv import load_dotenv
    except ImportError:
        print("❌ pip install -r requirements.txt 를 먼저 실행하세요.")
        return 1

    load_dotenv(HERE / ".env", override=True)
    import app_manifests as M
    import argo
    import gitsrv
    from k8s import Cluster

    if len(sys.argv) < 2 or sys.argv[1].startswith("-"):
        print("\n  사용 가능한 장애 시나리오\n")
        for k, v in M.SCENARIOS.items():
            print(f"   {k:<12} {v['title']}")
            print(f"   {'':<12} {v['hint']}\n")
        print("  사용법:  python break_it.py <이름>\n")
        return 0

    name = sys.argv[1]
    if name not in M.SCENARIOS:
        print(f"❌ 알 수 없는 시나리오: {name}")
        print("   사용 가능:", " · ".join(M.SCENARIOS))
        return 1

    sc = M.SCENARIOS[name]
    git = gitsrv.from_env()
    c = Cluster()

    # ── 0. 자동 동기화 확인 ────────────────────────────────────────────
    try:
        if argo.ensure_auto_sync(c):
            print("  (ArgoCD 자동 동기화가 꺼져 있어서 켰습니다)")
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠️  자동 동기화 설정을 확인하지 못했습니다: {str(e)[:120]}")

    # ── 1. 실제 커밋 ───────────────────────────────────────────────────
    print(f"\n▶ {sc['title']}")
    print(f"  커밋: {sc['commit']}")
    sha = git.put_file(M.MANIFEST_PATH, sc["manifest"](), sc["commit"])
    print(f"✅ 커밋 {sha} 생성")

    # ── 2. 즉시 감지 지시 ──────────────────────────────────────────────
    # 이게 없으면 ArgoCD 의 기본 폴링 주기를 기다려야 합니다.
    try:
        argo.refresh(c, hard=True)
        print("  ArgoCD 에 즉시 갱신을 요청했습니다")
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠️  refresh 요청 실패: {str(e)[:120]}")

    print(f"\n  예상 결과: {sc['expect']}")
    if "--no-wait" in sys.argv:
        print("\n  --no-wait 이므로 여기서 끝냅니다.  python status.py 로 확인하세요.\n")
        return 0

    print("  ArgoCD 가 적용하고 pod 가 반응할 때까지 지켜봅니다...\n")

    # ── 3. 관찰 ────────────────────────────────────────────────────────
    nudged = False
    last = None
    for elapsed in range(0, WAIT_SECONDS, 5):
        time.sleep(5)
        try:
            st = argo.status(c)
            line = f"sync={st['sync']:<12} health={st['health']:<12} rev={st['revision']}"
            if line != last:
                print(f"  [{elapsed:>3}초]  {line}")
                last = line

            reached = st["revision"].startswith(sha[:6])

            # 동기화가 실패하면 ArgoCD 는 같은 리비전을 자동 재시도하지 않습니다.
            # 그대로 두면 영원히 OutOfSync 로 멈춰 있으므로 즉시 알려야 합니다.
            if argo.sync_failed(st):
                print("\n❌ ArgoCD 동기화가 실패했습니다. 장애 주입이 아니라 배포 자체가 거부됐습니다.")
                if st["operation_message"]:
                    print(f"   {st['operation_message'][:400]}")
                for c in st["conditions"][:3]:
                    print(f"   {c}")
                print("\n   매니페스트가 잘못됐을 가능성이 높습니다. 확인:")
                print("     python kube.py app")
                print("     kubectl -n argocd get app kdt-dev-api -o yaml\n")
                return 1

            # 30초가 지나도 OutOfSync 로 멈춰 있으면 직접 동기화를 지시합니다
            if not nudged and elapsed >= 30 and st["sync"] == "OutOfSync":
                print("  자동 동기화가 안 걸려서 직접 동기화를 지시합니다")
                argo.sync_now(c)
                nudged = True

            if name == "healthy":
                if reached and st["health"] == "Healthy" and st["sync"] == "Synced":
                    print("\n✅ 정상 상태로 복구됐습니다.\n")
                    return 0
            elif reached and pods_broken(c):
                print("\n✅ 장애가 실제로 발생했습니다.\n")
                print("     python status.py      상태 확인")
                print("     python agent.py       에이전트 진단\n")
                return 0
        except Exception as e:  # noqa: BLE001
            print(f"  (상태 조회 실패: {str(e)[:90]})")

    print("\n⚠️  예상한 장애가 발생하지 않았습니다.")
    print("     매니페스트는 적용됐지만 pod 가 멀쩡할 수 있습니다.")
    print("     (예: nginx 가 낮은 메모리 한도를 견디는 경우)")
    print()
    print("     python status.py      현재 상태")
    print("     python kube.py pods   pod 상세")
    print("     python kube.py events 이벤트")
    print()
    print("     계속 안 죽으면 app_manifests.py 의 해당 시나리오 값을 더 극단적으로 바꾸세요.")
    print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
