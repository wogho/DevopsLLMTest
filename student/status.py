#!/usr/bin/env python3
"""
지금 클러스터가 어떤 상태인지 한 화면에 보여줍니다.

    python status.py

에이전트가 도구로 보는 것과 똑같은 정보입니다.
에이전트를 돌리기 전후로 실행해서 실제 변화를 눈으로 확인하세요.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
    import argo
    import tools
    from k8s import Cluster

    print("\n" + "═" * 62)
    app = tools.get_application()
    c = Cluster()
    pol = argo.sync_policy(c)
    auto = "켜짐" if pol.get("automated") else "꺼짐 ⚠️"
    ast = argo.status(c)
    print(f"  ArgoCD  {app['name']}")
    print(f"    sync   {app['sync_status']}   revision {app['revision']}")
    print(f"    health {app['health_status']}")
    print(f"    자동동기화 {auto}")
    if argo.sync_failed(ast):
        print(f"    ❌ 동기화 실패  phase={ast['phase']}")
        if ast["operation_message"]:
            print(f"       {ast['operation_message'][:180]}")
        for cond in ast["conditions"][:2]:
            print(f"       {cond[:180]}")
    if app["health_message"]:
        print(f"           {app['health_message'][:100]}")

    print("\n  Pods")
    for p in tools.list_pods()["pods"]:
        extra = ""
        if p["last_terminated_reason"]:
            extra = f"  (직전 종료: {p['last_terminated_reason']} exit={p['last_exit_code']})"
        print(f"    {p['name']:<42} {str(p['phase']):<10} ready={str(p['ready']):<6} "
              f"restarts={p['restarts']}  {p['state']}{extra}")

    print("\n  최근 이벤트")
    for e in tools.get_events(8)["events"]:
        mark = "!" if e["type"] == "Warning" else " "
        print(f"   {mark} {e['reason']:<22} {e['object']:<38} {e['message'][:70]}")

    print("\n  최근 커밋")
    for c in tools.get_recent_changes(4)["commits"]:
        print(f"    {c['sha']}  {c['message'][:64]}")
    print("═" * 62 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
