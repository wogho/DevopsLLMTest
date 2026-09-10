#!/usr/bin/env python3
"""
kubectl 없이 클러스터를 들여다봅니다. 액세스 키만 있으면 바로 됩니다.

    python kube.py pods                  kdt-dev 네임스페이스 pod
    python kube.py pods -A               전체 네임스페이스
    python kube.py pods argocd           특정 네임스페이스
    python kube.py nodes
    python kube.py events                최근 이벤트
    python kube.py logs <pod이름>         로그
    python kube.py logs <pod이름> -p      직전 컨테이너 로그
    python kube.py app                   ArgoCD Application 상태
    python kube.py res                   파드의 리소스 한도와 실행 명령
    python kube.py svc                   LoadBalancer 주소 확인
    python kube.py raw /api/v1/nodes     아무 API 경로나 직접

에이전트의 도구가 보는 것과 정확히 같은 데이터입니다.
kubectl 이 있으면 그걸 쓰셔도 됩니다. 이건 설치 없이 되는 대체재입니다.
"""

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def age(ts):
    return (ts or "")[11:19]


def main():
    from dotenv import load_dotenv

    load_dotenv(HERE / ".env", override=True)
    from k8s import Cluster

    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    flags = {a for a in sys.argv[1:] if a.startswith("-")}
    cmd = args[0] if args else "pods"
    default_ns = os.getenv("APP_NAMESPACE", "kdt-dev")
    c = Cluster()

    if cmd == "raw":
        print(json.dumps(c.get(args[1]), indent=2, ensure_ascii=False)[:8000])
        return 0

    if cmd == "nodes":
        nodes = c.get("/api/v1/nodes")["items"]
        print(f"\n  노드 {len(nodes)}개\n")
        for n in nodes:
            ready = next(
                (x["status"] for x in n["status"]["conditions"] if x["type"] == "Ready"), "?"
            )
            info = n["status"]["nodeInfo"]
            print(f"    {n['metadata']['name']:<50} Ready={ready}  {info['osImage']}")
        print()
        return 0

    if cmd == "pods":
        ns = args[1] if len(args) > 1 else default_ns
        if "-A" in flags:
            items = c.get("/api/v1/pods")["items"]
        else:
            items = c.pods(ns)
        print(f"\n  {'NAMESPACE':<12} {'POD':<46} {'PHASE':<10} READY  RESTART  STATE")
        for p in items:
            st = p["status"]
            for cs in st.get("containerStatuses", []) or [{}]:
                state = cs.get("state", {})
                reason = ""
                for k in ("waiting", "terminated"):
                    if k in state:
                        reason = state[k].get("reason", "")
                last = cs.get("lastState", {}).get("terminated", {})
                extra = (
                    f"  ← 직전 {last.get('reason')} exit={last.get('exitCode')}"
                    if last.get("reason")
                    else ""
                )
                print(
                    f"  {p['metadata']['namespace']:<12} {p['metadata']['name']:<46} "
                    f"{str(st.get('phase')):<10} {str(cs.get('ready')):<6} "
                    f"{cs.get('restartCount', 0):<8} {reason or 'Running'}{extra}"
                )
        print()
        return 0

    if cmd == "events":
        ns = args[1] if len(args) > 1 else default_ns
        print(f"\n  {ns} 최근 이벤트\n")
        for e in c.events(ns, 30)[:25]:
            mark = "!" if e.get("type") == "Warning" else " "
            obj = e.get("involvedObject", {})
            print(
                f"  {mark} {age(e.get('lastTimestamp')):<9} {e.get('reason', ''):<22} "
                f"{obj.get('kind','')}/{obj.get('name','')[:34]:<36} {(e.get('message') or '')[:70]}"
            )
        print()
        return 0

    if cmd == "logs":
        if len(args) < 2:
            print("  사용법: python kube.py logs <pod이름> [-p]")
            return 1
        prev = "-p" in flags
        try:
            text = c.pod_logs(default_ns, args[1], tail=80, previous=prev)
        except Exception as e:  # noqa: BLE001
            print(f"  로그를 못 가져왔습니다: {str(e)[:200]}")
            print("  컨테이너가 시작되지 않았을 수 있습니다. python kube.py events 를 보세요.")
            return 1
        print(f"\n  ── {args[1]} {'(직전 컨테이너)' if prev else ''} ──")
        print(text or "  (비어 있음)")
        return 0

    if cmd == "app":
        app = c.argo_app(os.getenv("APP_NAME", "kdt-dev-api"))
        st = app.get("status", {})
        print(f"\n  ArgoCD Application  {app['metadata']['name']}")
        print(f"    sync   {st.get('sync', {}).get('status')}   rev {(st.get('sync', {}).get('revision') or '')[:8]}")
        print(f"    health {st.get('health', {}).get('status')}")
        pol = app.get("spec", {}).get("syncPolicy") or {}
        print(f"    syncPolicy {pol if pol else '(없음 — 자동 동기화 꺼짐)'}")
        if st.get("health", {}).get("message"):
            print(f"           {st['health']['message'][:120]}")
        print("\n    리소스")
        for r in st.get("resources", []):
            print(f"      {r.get('kind','')}/{r.get('name','')}  {r.get('status','')}  "
                  f"{(r.get('health') or {}).get('status','')}")
        print()
        return 0

    if cmd == "res":
        ns = args[1] if len(args) > 1 else default_ns
        print(f"\n  {ns} 파드의 리소스 설정과 실행 명령\n")
        for p in c.pods(ns):
            print(f"  {p['metadata']['name']}")
            for ct in p["spec"]["containers"]:
                r = ct.get("resources", {})
                print(f"    requests {r.get('requests', {})}")
                print(f"    limits   {r.get('limits', {})}")
                if ct.get("args"):
                    print(f"    args     {str(ct['args'])[:110]}")
            print()
        return 0

    if cmd == "svc":
        print("\n  LoadBalancer 주소")
        for ns, name in (("argocd", "argocd-server"), ("git", "gitea-lb"),
                         ("git", "gitlab-nginx-ingress-controller")):
            try:
                host = c.service_host(ns, name)
                if host:
                    print(f"    {ns}/{name:<34} {host}")
            except Exception:  # noqa: BLE001
                pass
        print()
        return 0

    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
