#!/usr/bin/env python3
"""
학생 계정에 실습용 IAM 사용자와 액세스 키를 만듭니다.
각 학생 계정 자격증명으로 한 번씩 실행하세요.

    python create_student_user.py steve --profile student1
    python create_student_user.py minji --profile student2

출력된 네 줄을 해당 학생에게 1:1로 전달하면 됩니다.
학생은 그 값을 .env 에 붙여넣고 python deploy_lab.py 만 실행하면 끝입니다. (25~35분)

정리:
    python create_student_user.py steve --profile student1 --delete

여러 명을 한 번에:
    python create_student_user.py steve minji jaehyun --profile student1
    (같은 계정에 여러 사용자를 만들 때만 의미가 있습니다)
"""

import argparse
import json
import re
import sys
from pathlib import Path

POLICY_NAME = "kdt-lab-student"
POLICY_FILE = Path(__file__).resolve().parent / "student-iam-policy.json"


def ensure_policy(iam, account):
    arn = f"arn:aws:iam::{account}:policy/{POLICY_NAME}"
    try:
        iam.get_policy(PolicyArn=arn)
        print(f"  정책 {POLICY_NAME} 이미 있음")
    except iam.exceptions.NoSuchEntityException:
        iam.create_policy(
            PolicyName=POLICY_NAME,
            Description="DevOps LLM 에이전트 실습용 최소 권한",
            PolicyDocument=POLICY_FILE.read_text(encoding="utf-8"),
        )
        print(f"  정책 {POLICY_NAME} 생성")
    return arn


def delete_user(iam, user, policy_arn):
    try:
        for k in iam.list_access_keys(UserName=user)["AccessKeyMetadata"]:
            iam.delete_access_key(UserName=user, AccessKeyId=k["AccessKeyId"])
        try:
            iam.detach_user_policy(UserName=user, PolicyArn=policy_arn)
        except iam.exceptions.NoSuchEntityException:
            pass
        iam.delete_user(UserName=user)
        print(f"  ✅ {user} 삭제 완료")
    except iam.exceptions.NoSuchEntityException:
        print(f"  {user} 없음 — 건너뜁니다")


def create_user(iam, user, policy_arn, name):
    try:
        iam.get_user(UserName=user)
        print(f"  {user} 이미 있음 — 기존 키를 폐기하고 새로 발급합니다")
        for k in iam.list_access_keys(UserName=user)["AccessKeyMetadata"]:
            iam.delete_access_key(UserName=user, AccessKeyId=k["AccessKeyId"])
    except iam.exceptions.NoSuchEntityException:
        iam.create_user(
            UserName=user, Tags=[{"Key": "purpose", "Value": "devops-llm-agent-lab"}]
        )
        print(f"  {user} 생성")

    iam.attach_user_policy(UserName=user, PolicyArn=policy_arn)
    key = iam.create_access_key(UserName=user)["AccessKey"]
    return key["AccessKeyId"], key["SecretAccessKey"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+", help="학생 이름 (영문/숫자/하이픈 2~24자)")
    ap.add_argument("--profile", help="이 학생 계정의 AWS 프로파일")
    ap.add_argument("--region", default="ap-northeast-2")
    ap.add_argument("--delete", action="store_true", help="사용자와 키를 정리")
    ap.add_argument("--out", help="결과를 이 폴더에 <이름>.txt 로도 저장")
    args = ap.parse_args()

    for n in args.names:
        if not re.fullmatch(r"[A-Za-z0-9-]{2,24}", n):
            print(f"❌ 이름은 영문/숫자/하이픈 2~24자여야 합니다: '{n}'")
            return 1

    try:
        import boto3
    except ImportError:
        print("❌ boto3 가 필요합니다.  pip install boto3")
        return 1

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    try:
        account = session.client("sts").get_caller_identity()["Account"]
    except Exception as e:  # noqa: BLE001
        print(f"❌ AWS 인증 실패: {type(e).__name__}: {str(e)[:160]}")
        return 1

    iam = session.client("iam")
    print(f"\n▶ 계정 {account}")
    policy_arn = f"arn:aws:iam::{account}:policy/{POLICY_NAME}"

    if args.delete:
        for n in args.names:
            delete_user(iam, f"kdt-lab-{n}", policy_arn)
        return 0

    policy_arn = ensure_policy(iam, account)

    for n in args.names:
        key_id, secret = create_user(iam, f"kdt-lab-{n}", policy_arn, n)
        block = (
            f"STUDENT_NAME={n}\n"
            f"AWS_ACCESS_KEY_ID={key_id}\n"
            f"AWS_SECRET_ACCESS_KEY={secret}\n"
            f"AWS_DEFAULT_REGION={args.region}\n"
        )
        print("\n" + "─" * 62)
        print(f" {n} 님에게 1:1로 전달할 내용   (계정 {account})")
        print("─" * 62)
        print(block, end="")
        print("─" * 62)

        if args.out:
            d = Path(args.out)
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{n}.txt").write_text(block, encoding="utf-8")
            print(f" 저장: {d / (n + '.txt')}")

    print("\n이 네 줄을 .env 위쪽에 붙여넣고 python deploy_lab.py 를 실행하면 끝입니다.")
    print("채널에 통째로 올리지 마세요.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
