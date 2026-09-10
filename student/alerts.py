#!/usr/bin/env python3
"""
진단 리포트를 받을 알림 채널을 관리합니다.

    python alerts.py                     현재 구독 상태 확인
    python alerts.py you@company.com     이메일 구독 추가
    python alerts.py --test              테스트 메시지 발송
    python alerts.py --remove you@x.com  구독 해제

에이전트의 send_report 는 SNS 토픽에 발행합니다.
**구독자가 없으면 발행은 성공하지만 아무도 받지 못합니다.**
SNS 는 원래 그렇게 동작합니다. 받을 사람을 등록해야 메일이 옵니다.

이메일을 추가하면 AWS 가 확인 메일을 보냅니다.
**그 메일의 Confirm subscription 링크를 눌러야** 실제로 수신됩니다.
"""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

OK, NG, WARN = "\033[92m✅\033[0m", "\033[91m❌\033[0m", "\033[93m⚠️ \033[0m"


def main():
    try:
        import boto3
        from dotenv import load_dotenv
    except ImportError:
        print(f"{NG} pip install -r requirements.txt 를 먼저 실행하세요.")
        return 1

    load_dotenv(HERE / ".env", override=True)
    arn = os.getenv("ALERT_TOPIC_ARN", "")
    if not arn:
        print(f"{NG} .env 에 ALERT_TOPIC_ARN 이 없습니다.")
        print("   python deploy_lab.py 를 먼저 실행하세요.")
        return 1

    sns = boto3.Session(
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_DEFAULT_REGION"),
    ).client("sns")

    def show():
        subs = sns.list_subscriptions_by_topic(TopicArn=arn)["Subscriptions"]
        print(f"\n  토픽  {arn}")
        if not subs:
            print(f"\n  {WARN}구독자가 없습니다.")
            print("  에이전트가 보고해도 아무도 받지 못합니다.\n")
            print("  추가하려면:  python alerts.py you@company.com\n")
            return
        print(f"\n  구독자 {len(subs)}명\n")
        for s in subs:
            confirmed = s["SubscriptionArn"].startswith("arn:")
            mark = OK if confirmed else WARN
            note = "" if confirmed else "  ← 확인 메일의 링크를 눌러주세요"
            print(f"    {mark} {s['Protocol']:<8} {s['Endpoint']}{note}")
        print()

    # ── 테스트 발송 ────────────────────────────────────────────────────
    if "--test" in sys.argv:
        sns.publish(
            TopicArn=arn,
            Subject=f"[{os.getenv('STUDENT_NAME', 'lab')}] 알림 테스트",
            Message=(
                "이 메일이 보이면 에이전트의 진단 리포트도 정상적으로 도착합니다.\n\n"
                "— DevOps LLM 에이전트 실습"
            ),
        )
        print(f"\n{OK} 테스트 메시지를 발행했습니다.")
        print("  구독이 확인된 주소로 메일이 갑니다. 몇 초 걸릴 수 있습니다.\n")
        show()
        return 0

    # ── 구독 해제 ──────────────────────────────────────────────────────
    if "--remove" in sys.argv:
        idx = sys.argv.index("--remove") + 1
        if idx >= len(sys.argv):
            print(f"{NG} 해제할 주소를 지정하세요.")
            return 1
        target = sys.argv[idx]
        for s in sns.list_subscriptions_by_topic(TopicArn=arn)["Subscriptions"]:
            if s["Endpoint"] == target and s["SubscriptionArn"].startswith("arn:"):
                sns.unsubscribe(SubscriptionArn=s["SubscriptionArn"])
                print(f"{OK} {target} 구독 해제")
                return 0
        print(f"{WARN}{target} 은(는) 확인된 구독이 아닙니다.")
        return 1

    # ── 구독 추가 ──────────────────────────────────────────────────────
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        show()
        return 0

    email = args[0]
    if "@" not in email:
        print(f"{NG} 이메일 주소여야 합니다: {email}")
        return 1

    existing = [
        s for s in sns.list_subscriptions_by_topic(TopicArn=arn)["Subscriptions"]
        if s["Endpoint"] == email
    ]
    if existing and existing[0]["SubscriptionArn"].startswith("arn:"):
        print(f"\n{OK} {email} 은(는) 이미 확인된 구독입니다.\n")
        return 0

    sns.subscribe(TopicArn=arn, Protocol="email", Endpoint=email, ReturnSubscriptionArn=True)
    print(f"\n{OK} {email} 구독을 요청했습니다.")
    print()
    print("  ★ AWS Notifications 로부터 확인 메일이 갑니다.")
    print("    제목: AWS Notification - Subscription Confirmation")
    print("    본문의 'Confirm subscription' 링크를 눌러야 실제로 수신됩니다.")
    print("    스팸함도 확인해보세요.")
    print()
    print("  확인 후 테스트:  python alerts.py --test")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
