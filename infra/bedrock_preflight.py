#!/usr/bin/env python3
"""
Bedrock 사전 점검 — D-7 에 가장 먼저 실행해야 하는 스크립트입니다.

왜 필요한가:
  Bedrock 은 서버리스 파운데이션 모델을 계정에 기본 활성화하지만,
  **Anthropic 모델만은 예외**로 계정마다 최초 1회 사용 목적 양식을 내야 합니다.

  수강생이 30개의 서로 다른 계정을 쓴다면 원칙적으로 30번이지만,
  AWS Organizations 의 **관리 계정에서 한 번 제출하면 모든 멤버 계정에 상속**됩니다.
  이걸 모르면 강의 당일에 30명이 동시에 막힙니다.

사용:
    python bedrock_preflight.py submit   --profile <조직관리계정>
    python bedrock_preflight.py verify   --profile <학생계정하나>
    python bedrock_preflight.py profiles --profile <아무계정>
"""

import argparse
import base64
import json
import sys

FORM_DEFAULT = {
    "companyName": "KDT",
    "companyWebsite": "https://example.com",
    "intendedUsers": "0",
    "industryOption": "Technology",
    "otherIndustryOption": "",
    "useCases": (
        "Internal DevOps operational automation training. Deployment anomaly diagnosis "
        "agent using tool use over GitLab, ArgoCD and Kubernetes telemetry."
    ),
}

HELP_ON_FAIL = """
       자주 나오는 원인:

       · marketplace / subscription / not authorized 문구
             이 계정에 Anthropic 사용 양식이 아직 반영되지 않았습니다.
             조직 관리 계정에서:  python bedrock_preflight.py submit --profile <관리계정>
             호출 주체에 aws-marketplace:Subscribe / ViewSubscriptions 권한도 필요합니다.

       · on-demand throughput isn't supported
             베이스 모델 ID를 쓴 것입니다. 추론 프로파일 ID로 바꾸세요.
             python bedrock_preflight.py profiles  로 확인할 수 있습니다.

       · 리전 미지원
             --region 을 바꿔 다시 시도하세요.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["submit", "verify", "profiles"])
    ap.add_argument("--profile")
    ap.add_argument("--region", default="ap-northeast-2")
    ap.add_argument("--model", default="global.anthropic.claude-haiku-4-5-20251001-v1:0")
    ap.add_argument("--company", default=FORM_DEFAULT["companyName"])
    ap.add_argument("--website", default=FORM_DEFAULT["companyWebsite"])
    args = ap.parse_args()

    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError:
        print("❌ boto3 가 필요합니다.  pip install boto3")
        return 1

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    try:
        me = session.client("sts").get_caller_identity()
    except Exception as e:  # noqa: BLE001
        print(f"❌ AWS 인증 실패: {type(e).__name__}: {str(e)[:160]}")
        return 1

    # ── 최초 사용 양식 제출 ────────────────────────────────────────────────
    if args.command == "submit":
        print("\n▶ Anthropic 최초 사용 양식 제출")
        print(f"  계정 {me['Account']}   {me['Arn']}")
        ans = input("  이 계정이 AWS Organizations 관리 계정이 맞습니까? [y/N] ").strip().lower()
        if ans != "y":
            print("  중단합니다. 관리 계정에서 실행해야 멤버 계정에 상속됩니다.")
            return 1

        form = dict(FORM_DEFAULT, companyName=args.company, companyWebsite=args.website)
        payload = base64.b64encode(json.dumps(form).encode("utf-8")).decode("ascii")
        try:
            session.client("bedrock").put_use_case_for_model_access(formData=payload)
        except ClientError as e:
            print(f"❌ 제출 실패: {e.response['Error']['Code']}")
            print(f"   {e.response['Error']['Message'][:300]}")
            print("   콘솔에서도 가능합니다: Bedrock → Model access → Submit use case details")
            return 1
        except AttributeError:
            print("❌ 이 boto3 버전은 put_use_case_for_model_access 를 지원하지 않습니다.")
            print("   pip install -U boto3  후 다시 시도하거나, Bedrock 콘솔에서 제출하세요.")
            return 1

        print("✅ 제출 완료. 멤버 계정에 반영되기까지 잠깐 걸릴 수 있습니다.")
        print("   다음:  python bedrock_preflight.py verify --profile <학생계정>")
        return 0

    # ── 사용 가능한 추론 프로파일 ──────────────────────────────────────────
    if args.command == "profiles":
        print(f"\n▶ {args.region} 에서 사용 가능한 Claude 추론 프로파일")
        try:
            items = session.client("bedrock").list_inference_profiles()[
                "inferenceProfileSummaries"
            ]
        except ClientError as e:
            print(f"❌ 조회 실패: {e.response['Error']['Code']}")
            return 1
        found = [p for p in items if "claude" in p["inferenceProfileId"].lower()]
        if not found:
            print("  (없음) 리전을 바꿔 다시 확인해보세요.")
            return 1
        for p in found:
            mark = "★" if "haiku" in p["inferenceProfileId"] else " "
            print(f"  {mark} {p['inferenceProfileId']:<58} {p.get('status', '')}")
        print("\n  ★ 표시된 값을 학생 템플릿의 BedrockModelId 기본값에 반영하세요.")
        print("     infra/student/gen_template.py 의 BedrockModelId Default")
        return 0

    # ── 실제 호출 검증 ─────────────────────────────────────────────────────
    print(f"\n▶ 실제 모델 호출 검증   계정 {me['Account']}   {args.region}")
    print(f"  모델: {args.model}")
    try:
        r = session.client("bedrock-runtime").converse(
            modelId=args.model,
            messages=[{"role": "user", "content": [{"text": "Reply with OK only."}]}],
            inferenceConfig={"maxTokens": 8},
        )
        text = r["output"]["message"]["content"][0]["text"].strip()
        print(f"✅ 호출 성공 — 응답: {text}")
        return 0
    except ClientError as e:
        print(f"❌ 실패: {e.response['Error']['Code']}")
        print(f"   {e.response['Error']['Message'][:300]}")
        print(HELP_ON_FAIL)
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"❌ 실패: {type(e).__name__}: {str(e)[:200]}")
        print(HELP_ON_FAIL)
        return 1


if __name__ == "__main__":
    sys.exit(main())
