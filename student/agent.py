#!/usr/bin/env python3
"""
DevOps 진단 에이전트 — 실습 골격

    python agent.py
    python agent.py "kdt-dev-api 배포 상태 확인해줘"

TODO 가 5개 있습니다. 순서대로 채우면 동작합니다.
막히면 solution/agent.py 를 열어보세요. 부끄러운 일이 아닙니다.

이 에이전트는 **진짜 클러스터**를 조사합니다.
도구가 반환하는 로그와 이벤트는 실제로 지금 일어나고 있는 일입니다.

    [사람] "배포 이상 진단해줘"
       │
       ▼
    while True:
      1. 대화 전체를 Bedrock 에 보낸다
      2. 응답을 대화에 추가한다
      3. stopReason 을 본다
           tool_use → 도구 실행 (쓰기 도구는 사람 승인) → 결과 되돌림 → 계속
           그 외    → 종료
"""

import json
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

import tools  # noqa: E402

MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "global.anthropic.claude-haiku-4-5-20251001-v1:0")
REGION = os.getenv("AWS_DEFAULT_REGION", "ap-northeast-2")
MAX_TURNS = 14

bedrock = boto3.client("bedrock-runtime", region_name=REGION)


# ===========================================================================
# TODO 1 — 시스템 프롬프트
# ===========================================================================
#
# 정답이 없는 유일한 부분이고, 결과 차이가 가장 크게 벌어지는 부분입니다.
#
# 생각해볼 것:
#   - 이 에이전트는 누구이고 지금 어떤 상황에 있는가?
#   - 어떤 순서로 조사해야 하는가? (순서를 안 주면 도구를 마구 부릅니다)
#   - 로그가 비어 있을 때 무엇을 봐야 하는가?
#   - 추측과 사실을 어떻게 구분해서 보고할 것인가?
#   - 언제 되돌리기를 제안하고, 언제 사람에게 넘겨야 하는가?
#   - 언제 멈춰야 하는가?

SYSTEM_PROMPT = """
TODO: 여기에 시스템 프롬프트를 작성하세요.

이대로 두면 아주 밋밋한 리포트가 나옵니다.

당신은 DevOps 진단 어시스턴트입니다. 배포 이상의 원인을 조사하고 보고하세요.
"""


# ===========================================================================
# TODO 2 — 도구 설정
# ===========================================================================
# Bedrock Converse API 는 도구 목록을 {"tools": [...]} 형태로 받습니다.
# tools.py 의 TOOL_SPECS 를 그대로 쓰면 됩니다.

TOOL_CONFIG = None  # TODO

if TOOL_CONFIG is None:
    print("⚠️  TOOL_CONFIG 가 아직 None 입니다. TODO 2 를 먼저 채워주세요.")


# ===========================================================================
# 제공되는 것들
# ===========================================================================
def converse_with_retry(**kwargs):
    """쓰로틀링 대비 지수 백오프. 에이전트 코드의 기본 장비입니다."""
    for attempt in range(6):
        try:
            return bedrock.converse(**kwargs)
        except ClientError as e:
            if e.response["Error"]["Code"] != "ThrottlingException":
                raise
            wait = (2**attempt) + random.random()
            print(f"   [쓰로틀링] {wait:.1f}초 후 재시도")
            time.sleep(wait)
    raise RuntimeError("재시도 한도를 초과했습니다.")


def require_approval(name, args):
    """쓰기 도구는 사람이 승인해야 실행됩니다. 실무에서는 Slack 버튼이 이 자리입니다."""
    print("\n" + "=" * 62)
    print(f"⚠️  승인 필요: {name}")
    print("=" * 62)
    preview = args.get("text") or args.get("reason") or json.dumps(args, ensure_ascii=False)
    print(str(preview)[:1200])
    print("=" * 62)
    return input("실행할까요? [y/N] ").strip().lower() == "y"


def to_json_block(result):
    """Bedrock 의 json 블록은 최상위가 객체여야 합니다."""
    return result if isinstance(result, dict) else {"items": result}


# ===========================================================================
def run(user_request):
    messages = [{"role": "user", "content": [{"text": user_request}]}]
    total_in = total_out = 0

    for turn in range(MAX_TURNS):
        print(f"\n─── turn {turn + 1} ───")

        # ── TODO 3 — Bedrock 호출 ─────────────────────────────────────
        # converse_with_retry() 에 넘길 것:
        #   modelId=MODEL_ID
        #   messages=messages
        #   system=[{"text": SYSTEM_PROMPT}]
        #   toolConfig=TOOL_CONFIG
        #   inferenceConfig={"maxTokens": 2048, "temperature": 0}
        response = None  # TODO 3

        if response is None:
            print("\n" + "─" * 58)
            print("  아직 TODO 3(Bedrock 호출)을 채우지 않았습니다.")
            print("  막히면:  python solution/agent.py")
            print("─" * 58 + "\n")
            return

        usage = response["usage"]
        total_in += usage["inputTokens"]
        total_out += usage["outputTokens"]

        output_message = response["output"]["message"]
        messages.append(output_message)

        for block in output_message["content"]:
            if "text" in block:
                print(f"[생각] {block['text'].strip()[:400]}")

        print(f"[stopReason] {response['stopReason']}")

        # ── TODO 4 — 종료 조건 ────────────────────────────────────────
        # stopReason 이 "tool_use" 가 아니면 루프를 빠져나가세요.
        # TODO 4

        # ── TODO 5 — 도구 실행 후 결과 되돌려주기 ─────────────────────
        # 각 toolUse 블록마다:
        #   1. 쓰기 도구(tools.WRITE_TOOLS)면 require_approval() 로 확인
        #   2. tools.run_tool(이름, 인자) 실행
        #   3. 결과를 아래 형태로 모아서
        #        {"toolResult": {"toolUseId": ..., "content": [{"json": ...}]}}
        #   4. messages 에 {"role": "user", "content": 결과리스트} 로 추가
        tool_results = []
        for block in output_message["content"]:
            if "toolUse" not in block:
                continue
            tool_use = block["toolUse"]
            print(f"[도구] {tool_use['name']}({json.dumps(tool_use['input'], ensure_ascii=False)[:120]})")
            # TODO 5

        # TODO 5 (이어서)

    print(f"\n토큰 사용량: 입력 {total_in:,} / 출력 {total_out:,}")
    return messages


if __name__ == "__main__":
    request = (
        " ".join(sys.argv[1:])
        or "kdt-dev-api 배포에 이상이 감지됐습니다. 원인을 조사하고 운영 채널에 보고해주세요."
    )
    print(f"요청: {request}")
    run(request)
