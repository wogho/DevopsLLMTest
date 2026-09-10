#!/usr/bin/env python3
"""
클러스터를 지켜보다가 장애가 나면 에이전트를 깨웁니다.

    python watch.py                          지켜보기만 (아무것도 실행하지 않음)
    python watch.py --agent --solution       완성본 에이전트를 자동 실행
    python watch.py --agent                  내가 채운 agent.py 를 자동 실행

"에이전트를 무엇이 깨우는가"는 그 자체로 설계 주제입니다.
여기서는 가장 단순한 폴링을 씁니다. 실무에서는 이 자리에
Alertmanager · ArgoCD Notifications · EventBridge 가 들어갑니다.
구조는 같습니다. 신호가 오면 루프를 시작한다.
"""

import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

INTERVAL = 15
BAD = {"Degraded", "Missing", "Unknown"}


def main():
    from dotenv import load_dotenv

    load_dotenv(HERE / ".env", override=True)
    import tools

    run_agent = "--agent" in sys.argv
    use_solution = "--solution" in sys.argv
    target = HERE / ("solution/agent.py" if use_solution else "agent.py")

    print(f"\n  지켜보는 중  ({INTERVAL}초 간격)   Ctrl+C 로 중단")
    if run_agent:
        print(f"  장애를 만나면 실행할 것:  {target.name}"
              f"{'  (정답)' if use_solution else '  (내가 만든 것)'}")
    else:
        print("  에이전트 자동 실행: 꺼짐   (--agent 로 켜기)")
    print()

    last = None
    fired = False
    while True:
        try:
            app = tools.get_application()
            health, sync = app["health_status"], app["sync_status"]
            state = f"{sync}/{health}"
            stamp = time.strftime("%H:%M:%S")

            if state != last:
                mark = "🔴" if health in BAD else "🟢" if health == "Healthy" else "🟡"
                print(f"  {stamp}  {mark} sync={sync:<12} health={health:<12} rev={app['revision']}")
                if app["health_message"]:
                    print(f"            {app['health_message'][:90]}")
                last = state

            if health in BAD and not fired:
                fired = True
                print(f"\n  {stamp}  ⚠️  장애 감지 — {health}")
                if run_agent:
                    print(f"  {target.name} 를 실행합니다.\n")
                    subprocess.run(
                        [sys.executable, str(target),
                         f"{app['name']} 이 {health} 상태입니다. 원인을 조사하고 보고해주세요."],
                        check=False,
                    )
                    print("\n  다시 지켜봅니다.\n")
                else:
                    print("  python agent.py 를 실행해보세요.")
                    print("  (--agent 로 켜두면 이 순간 자동으로 실행됩니다)\n")

            if health == "Healthy":
                fired = False

        except KeyboardInterrupt:
            print("\n  중단했습니다.\n")
            return 0
        except Exception as e:  # noqa: BLE001
            print(f"  (조회 실패: {str(e)[:100]})")

        time.sleep(INTERVAL)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  중단했습니다.\n")
