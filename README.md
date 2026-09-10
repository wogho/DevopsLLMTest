# DevOps 엔지니어를 위한 LLM 에이전트 설계

**실제 EKS 클러스터에서 진짜 장애를 일으키고, Bedrock 에이전트가 그것을 진단·복구합니다.**

---

## 무엇이 실제로 돌아가는가

```
[내 AWS 계정]
  EKS Auto Mode 클러스터
    ├─ argocd 네임스페이스     ArgoCD
    ├─ git 네임스페이스        Gitea (또는 GitLab CE)
    └─ kdt-dev 네임스페이스    실제 앱 (nginx Deployment + Service)

  Git 저장소 (클러스터 안)
    manifests/deployment.yaml  ← ArgoCD 가 이 파일을 보고 동기화

  SNS 토픽                     ← 에이전트가 진단 리포트를 보내는 곳
```

**장애는 모의가 아닙니다.** `break_it.py` 가 매니페스트를 실제로 커밋하면
ArgoCD 가 클러스터에 적용하고 pod 가 진짜로 죽습니다.
`kubectl get pods` 로 직접 확인할 수 있습니다.

| 시나리오 | 실제로 일어나는 일 |
|---|---|
| `healthy` | 정상. 에이전트가 '이상 없음'으로 판단하는지 보는 대조군 |
| `image-tag` | 존재하지 않는 태그 → 진짜 `ImagePullBackOff` |
| `oom` | 워밍업 48MB vs 한도 32Mi → 진짜 `OOMKilled`, exit 137 |
| `probe` | readiness 경로 변경 → 진짜 `Readiness probe failed 404` |
| `both` | 복합 장애 |

에이전트 도구 7개가 전부 실제 API 를 칩니다.

| 도구 | 무엇을 호출하나 | |
|---|---|---|
| `get_recent_changes` | Git 서버 REST API | 읽기 |
| `get_application` | Kubernetes API — ArgoCD Application CRD | 읽기 |
| `list_pods` | Kubernetes API | 읽기 |
| `get_pod_logs` | Kubernetes API (현재 + 직전 컨테이너) | 읽기 |
| `get_events` | Kubernetes API | 읽기 |
| `send_report` | SNS | **쓰기 · 사람 승인** |
| `rollback_last_change` | Git 커밋 되돌리기 → 실제 복구 | **쓰기 · 사람 승인** |

---

## 구성

```
.
├── infra/
│   ├── lab-stack.yaml            VPC + EKS Auto Mode + 부트스트랩 CodeBuild + SNS
│   ├── bedrock_preflight.py      ★ D-7 에 가장 먼저 실행
│   ├── student-iam-policy.json   학생 최소 권한
│   └── create_student_user.py    계정별 IAM 사용자 + 키 발급
│
├── student/                      강사와 학생이 똑같이 쓰는 폴더
│   ├── .env.example              키는 직접 / 나머지는 자동
│   ├── deploy_lab.py             ★ 인프라 전체 생성 (25~35분)
│   ├── check_env.py              환경 점검 (10항목)
│   ├── status.py                 지금 클러스터 상태 한 화면
│   ├── break_it.py               ★ 실제 장애 주입
│   ├── agent.py                  Lab (TODO 5개)
│   ├── solution/agent.py         정답
│   ├── watch.py                  장애 감지 → 에이전트 자동 실행
│   ├── cleanup.py                ★ 전부 삭제
│   │
│   ├── tools.py                  에이전트 도구 7개 (완성본)
│   ├── k8s.py                    EKS 인증 + Kubernetes REST 클라이언트
│   ├── argo.py                   ArgoCD 제어 (refresh · sync · 상태)
│   ├── gitsrv.py                 Gitea / GitLab 공통 래퍼
│   ├── app_manifests.py          앱 매니페스트 + 시나리오 정의
│   │
│   ├── kube.py                   kubectl 없이 클러스터 조회
│   ├── grant_access.py           다른 IAM 주체에 클러스터 접근 권한 부여
│   └── argocd_password.py        ArgoCD UI 접속 정보
│
└── docs/
    ├── 수강생_실행순서.md        ★ 명령 하나하나 무엇이 일어나는지
    ├── TODO_해설.md              agent.py 빈칸 정답 (강사용)
    ├── 강사노트.md
    └── 참가자_사전안내문.md
```

---

## 시작하기

### 1. 준비

**Windows (PowerShell)**

```powershell
cd student
python -m venv .venv
.venv\Scripts\Activate.ps1          # 실행 정책 오류 시 아래 참고
pip install -r requirements.txt
copy .env.example .env
```

> 실행 정책 오류가 나면 그 창에서만 한 번 풀어주면 됩니다.
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`
>
> 가상환경이 번거로우면 건너뛰어도 됩니다. 패키지가 세 개뿐이라 전역 설치해도 무방합니다.
> `python -m pip install -r requirements.txt`

**macOS / Linux**

```bash
cd student
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` 위쪽에 받은 값을 채웁니다.

```
STUDENT_NAME=steve                 소문자/숫자/하이픈 2~20자
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=ap-northeast-2
ALERT_EMAIL=you@company.com        비우면 SNS 메일이 안 옵니다
```

### 2. 배포 (25~35분)

```bash
python deploy_lab.py
python check_env.py                # 10항목 전부 ✅
```

AWS CLI 는 필요 없습니다. boto3 로 직접 배포합니다.

### 3. 실습

```bash
python status.py               지금 상태 (정상)
python break_it.py             장애 목록 보기
python break_it.py oom         실제로 장애 발생
python status.py               진짜 죽은 것 확인
python agent.py                에이전트가 진단
python status.py               복구됐는지 확인
```

자동 감지까지 보고 싶으면 터미널 두 개로:

```bash
python watch.py --agent        # 지켜보기
python break_it.py probe       # 장애를 일으키면 알아서 깨어납니다
```

### 4. 정리 — 반드시

```bash
python cleanup.py
```

**EKS 클러스터는 켜두면 계속 요금이 나갑니다.**

---

## 알림이 안 오면

에이전트의 `send_report` 는 SNS 토픽에 발행합니다.
**구독자가 없으면 발행은 성공하지만 아무도 받지 못합니다.**

```bash
python alerts.py                     현재 구독 상태
python alerts.py you@company.com     이메일 추가
python alerts.py --test              테스트 발송
```

이메일을 추가하면 AWS 가 확인 메일을 보냅니다.
**`Confirm subscription` 링크를 눌러야** 실제로 수신됩니다. 스팸함도 확인하세요.

`.env` 의 `ALERT_EMAIL` 을 채우고 배포하면 처음부터 구독이 만들어집니다.

---

## 클러스터를 직접 들여다보기

설치 없이 바로 되는 방법:

```bash
python kube.py pods -A          전체 파드
python kube.py nodes            노드
python kube.py events           최근 이벤트
python kube.py logs <pod> -p    직전 컨테이너 로그
python kube.py app              ArgoCD Application + syncPolicy
python kube.py svc              LoadBalancer 주소
```

**CloudShell / 콘솔에서 kubectl 을 쓰려면** 접근 권한을 한 번 더 줘야 합니다.
EKS 는 IAM 주체 단위로 접근을 관리하는데(access entry), 스택을 만든 액세스 키 사용자에게만
권한이 붙어 있어서 콘솔 로그인 주체로는 401 이 납니다.

```bash
# CloudShell 에서 내 주체 ARN 확인
aws sts get-caller-identity --query Arn --output text

# 노트북에서 권한 부여 (SSO 세션 ARN 을 그대로 붙여넣어도 자동 변환됩니다)
python grant_access.py arn:aws:sts::111122223333:assumed-role/AWSReservedSSO_.../me@corp.com

# 다시 CloudShell 에서
aws eks update-kubeconfig --name kdt-devops-lab --region ap-northeast-2
kubectl get pods -A
```

`python grant_access.py --list` 로 현재 접근 가능한 주체를 볼 수 있습니다.
다음 배포부터는 `.env` 의 `EXTRA_ADMIN_ARN` 에 적어두면 처음부터 들어갑니다.

---

## 문제가 생기면

먼저 이 두 개를 보세요. 대부분 여기서 원인이 나옵니다.

```bash
python status.py            ArgoCD sync/health + 동기화 실패 사유 + pod + 이벤트
python kube.py events       쿠버네티스 이벤트 원본
```

### 실제로 겪은 문제들

| 증상 | 원인 | 조치 |
|---|---|---|
| 스택 생성 실패 `AccessEntry ... already in use` | `BootstrapClusterCreatorAdminPermissions` 자동 생성과 충돌 | 템플릿에서 `false` 로 되어 있는지 확인 |
| 부트스트랩 실패 `may not be set to 'None' for LoadBalancer` | Gitea 의 `gitea-http` 는 headless 서비스 | 별도 `gitea-lb` 서비스를 만드는 방식으로 수정됨 |
| Gitea PVC 가 Pending | EKS Auto Mode 는 기본 StorageClass 를 안 만듦 | 부트스트랩이 `auto-ebs-sc` 를 만듭니다 |
| LoadBalancer 주소가 안 붙음 | Auto Mode 는 어노테이션이 필요 | `aws-load-balancer-type: external` 이 붙어 있는지 |
| CloudShell 에서 401 | 다른 IAM 주체 | `python grant_access.py <ARN>` |
| `invalid principal` | SSO 역할은 경로(path)를 가짐 | 최신 `grant_access.py` 가 IAM 에서 실제 ARN 을 조회합니다 |
| ArgoCD 가 `OutOfSync` 로 멈춤 | **동기화가 실패한 것.** ArgoCD 는 같은 리비전을 자동 재시도하지 않습니다 | `python status.py` 에 실패 사유가 표시됩니다 |
| 매니페스트 거부 `must be less than or equal to memory limit` | memory request 가 limit 보다 큼 | `app_manifests.py` 가 limit 에 맞춰 request 를 낮춥니다 |
| pod 가 안 죽음 (oom) | nginx 는 메모리를 거의 안 써서 한도만 낮춰선 안 죽습니다 | 앱이 기동 시 48MB 를 쓰도록 되어 있고, 한도를 32Mi 로 낮춰 부딪히게 합니다 |
| 장애가 안 났는데 성공이라고 나옴 | 롤링 업데이트 중 새 pod 가 잠깐 미준비 | 수정됨 — 45초 이상 지속돼야 장애로 셉니다 |
| Bedrock `marketplace` 언급 | 계정별 Anthropic 최초 사용 양식 미제출 | `infra/bedrock_preflight.py submit` (조직 관리 계정) |

---

## 비용

| 항목 | 시간당 |
|---|---|
| EKS 컨트롤플레인 | $0.10 |
| Auto Mode 노드 (소형 1~2대) | $0.05 ~ $0.15 |
| NLB 2개 (ArgoCD · Git) | $0.05 |
| Bedrock Haiku | 무시할 수준 |

4시간 실습 기준 계정당 **약 $1~2**. 지우지 않으면 하루 $5 씩 쌓입니다.

---

## 슬라이드

강의 슬라이드는 이 실물 아키텍처에 맞춰 다시 작성 중입니다.
이전 버전(모의 환경 기준)은 내용이 맞지 않아 이 패키지에서 제외했습니다.
