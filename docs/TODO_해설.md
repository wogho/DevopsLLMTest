# 강사용 — agent.py TODO 5개 해설

학생이 `agent.py` 에서 채우는 다섯 군데의 정답과, 각각에서 무엇을 짚어야 하는지 정리했습니다.
정답 전체는 `student/solution/agent.py` 에 있습니다.

**진행 요령:** TODO 2~5 를 먼저 채우게 해서 일단 돌아가게 만든 다음, TODO 1(프롬프트)에
시간을 쓰게 하세요. 순서를 반대로 하면 프롬프트를 고쳐도 결과를 볼 수 없어 학습이 안 됩니다.

---

## TODO 2 — 도구 설정  (2분)

가장 쉽습니다. 여기서 먼저 성취감을 주고 시작합니다.

```python
TOOL_CONFIG = {"tools": tools.TOOL_SPECS}
```

**짚을 것:** Bedrock Converse API 는 도구 목록을 `{"tools": [...]}` 형태로 받습니다.
`tools.py` 를 열어 `TOOL_SPECS` 안의 `description` 을 한 번 읽어보게 하세요.
LLM 이 그 도구에 대해 아는 것은 그 설명 한 덩어리가 전부입니다.

---

## TODO 3 — Bedrock 호출  (5분)

```python
response = converse_with_retry(
    modelId=MODEL_ID,
    messages=messages,
    system=[{"text": SYSTEM_PROMPT}],
    toolConfig=TOOL_CONFIG,
    inferenceConfig={"maxTokens": 2048, "temperature": 0},
)
```

**짚을 것**

- `messages` 는 **대화 전체**입니다. 모델에는 기억이 없어서 매 턴 통째로 다시 보냅니다.
  그래서 1턴에서 흘린 토큰이 끝까지 따라다니고, 그게 곧 비용입니다.
- `system` 은 리스트입니다. `[{"text": ...}]` — 문자열을 그냥 넣으면 오류가 납니다.
- `temperature=0` 은 진단 작업이라 그렇습니다. 창작이 아니라 사실 확인이 목적입니다.
- `converse_with_retry` 는 제공됩니다. 지수 백오프가 왜 기본 장비인지는 A블록에서 다룹니다.

---

## TODO 4 — 종료 조건  (2분)

```python
if response["stopReason"] != "tool_use":
    break
```

**짚을 것:** 이 한 줄이 루프의 **유일한 분기점**입니다.
`stopReason` 이 `tool_use` 면 모델이 도구를 부르고 싶다는 뜻이고,
`end_turn` 이면 할 말을 다 했다는 뜻입니다.

"에이전트를 만든다"는 말의 실체가 이 `if` 문 하나라는 걸 여기서 짚으면 반응이 좋습니다.

---

## TODO 5 — 도구 실행과 결과 반환  (10분)

가장 길고, 가장 많이 틀립니다.

```python
tool_results = []
for block in output_message["content"]:
    if "toolUse" not in block:
        continue
    u = block["toolUse"]
    name, args = u["name"], u["input"]
    print(f"[도구] {name}({json.dumps(args, ensure_ascii=False)[:140]})")

    # 쓰기 도구는 사람 승인을 받습니다
    if name in tools.WRITE_TOOLS and not require_approval(name, args):
        result = {"error": "사람이 실행을 거부했습니다. 다시 시도하지 말고 종료하세요."}
    else:
        result = tools.run_tool(name, args)

    tool_results.append({
        "toolResult": {
            "toolUseId": u["toolUseId"],
            "content": [{"json": to_json_block(result)}],
        }
    })

messages.append({"role": "user", "content": tool_results})
```

### 여기서 나오는 실수 네 가지

| 실수 | 증상 | 설명 |
|---|---|---|
| `role` 을 `"assistant"` 로 | ValidationException | 도구 결과는 **외부에서 들어온 정보**입니다. 모델이 한 말이 아니므로 `user` 입니다 |
| `toolUseId` 를 안 넣거나 틀림 | ValidationException | 어느 요청에 대한 응답인지 짝을 맞추는 값입니다 |
| 도구 결과를 리스트로 그대로 | 400 오류 | `{"json": ...}` 의 최상위는 객체여야 합니다. `to_json_block()` 이 감싸줍니다 |
| 도구마다 `messages.append` | 대화가 깨짐 | 한 턴에 여러 도구를 부를 수 있습니다. **모아서 한 번에** 넣어야 합니다 |

첫 번째가 압도적으로 많습니다. 실습 순회할 때 이것부터 보세요.

### 승인 분기도 여기 있습니다

`tools.WRITE_TOOLS` 는 `send_report` 와 `rollback_last_change` 두 개입니다.
읽기 도구는 그냥 실행되고, 쓰기 도구만 사람에게 물어봅니다.

**거부했을 때 그냥 넘어가지 않고 `{"error": ...}` 를 모델에게 돌려주는 것**이 중요합니다.
그래야 모델이 "사람이 거부했구나"를 알고 다음 행동을 정합니다.
아무것도 안 돌려주면 모델은 계속 재시도합니다.

---

## TODO 1 — 시스템 프롬프트  (나머지 시간 전부)

**정답이 없는 유일한 부분이고, 결과 차이가 가장 크게 벌어지는 부분입니다.**

학생에게 정답을 주지 마세요. 대신 **들어가야 할 일곱 가지**를 칠판에 적어두고
각자 쓰게 합니다.

| | 요소 | 왜 필요한가 |
|---|---|---|
| 1 | 역할과 상황 고정 | "새벽 3시, 당직자가 이 보고를 읽는다" — 톤이 안 샙니다 |
| 2 | 조사 순서 강제 | 순서를 안 주면 도구를 마구 부릅니다. 순서가 곧 진단의 논리입니다 |
| 3 | 도구별 분기 조건 | "로그가 비면 이벤트를 봐라" 같은 지식을 심어줍니다 |
| 4 | 사실과 추측 분리 | 그럴듯한 거짓말을 줄이는 가장 효과적인 장치 |
| 5 | 출력 형식 고정 | 새벽에 깨어난 사람이 스캔할 수 있는 형태로 |
| 6 | 되돌리기 조건 | 자율성의 경계를 프롬프트로 긋습니다 |
| 7 | 종료 조건 | 무한 루프와 토큰 낭비 방지 |

### 3번이 이 실습의 숨은 핵심입니다

DevOps 엔지니어라면 다 아는 것이지만, 모델은 모릅니다.

```
- pod 가 재시작을 반복한다 → get_pod_logs 를 previous=true 로 호출하라.
  현재 로그는 비어 있고 원인은 직전 컨테이너에 있다.
- 로그가 정상인데 Ready 가 아니다 → get_events 를 보라.
  probe 실패와 이미지 pull 실패는 애플리케이션 로그에 절대 안 남는다.
- 이미지를 못 받는 pod 는 로그 자체가 없다. 반복 조회하지 말고 이벤트로 가라.
```

**"여러분이 아는 트러블슈팅 요령을 글로 옮기는 것"** 이 프롬프트 엔지니어링이라고
설명하면 가장 잘 통합니다.

### 비교 시연

프롬프트 없이 돌린 것과 넣고 돌린 것을 나란히 보여주세요.

```
없이:  kdt-dev-api 에 문제가 있습니다. 확인이 필요합니다.

있으면:
  [P1] kdt-dev-api — 메모리 한도 하향으로 OOMKilled
  ■ 확인된 사실
  · 커밋 1f9c7a3c: memory limit 128Mi → 8Mi (get_recent_changes)
  · pod 2개 CrashLoopBackOff, 직전 종료 OOMKilled exit 137 (list_pods)
  ■ 추정 원인  (확신도 높음)
  · 8Mi 는 nginx 기동에 부족. 직전 커밋이 직접 원인
  ■ 권고 조치
  1. 해당 커밋 되돌리기 또는 limit 을 64Mi 이상으로
```

**"두 사람 다 똑같은 도구 7개를 받았습니다."** 이 한마디가 이 실습의 결론입니다.

전체 예시는 `solution/agent.py` 의 `SYSTEM_PROMPT` 를 보세요.
학생에게는 실습이 끝난 뒤에 공개하시는 걸 권합니다.

---

## 시간 배분

| | 분 |
|---|---|
| TODO 2 · 3 · 4 | 10 |
| TODO 5 | 10 |
| 첫 실행 · 디버깅 | 5 |
| TODO 1 프롬프트 작성 | 15 |
| 리포트 비교 | 10 |

15분 지점에 TODO 2~5 정답을 화면에 띄우고 같이 읽으세요.
**끝까지 혼자 붙들게 두지 마세요.** 목표는 완주가 아니라 프롬프트에 시간을 쓰게 하는 것입니다.
