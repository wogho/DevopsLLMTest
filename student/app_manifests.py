"""
클러스터에 배포되는 실제 앱과, 장애를 만드는 변형들.

앱은 nginx 한 개입니다. 중요한 건 앱이 무엇이냐가 아니라
**진짜로 죽고, 진짜 로그와 이벤트가 남는다**는 점입니다.

시나리오는 매니페스트를 실제로 커밋해서 만듭니다.
ArgoCD 가 30초 안에 동기화하고, 그 결과로 pod 가 실제로 실패합니다.
"""

NAMESPACE = "kdt-dev"
APP = "kdt-dev-api"
IMAGE_REPO = "public.ecr.aws/nginx/nginx"
GOOD_TAG = "1.27"

MANIFEST_PATH = "manifests/deployment.yaml"


def _mi(value: str) -> int:
    """'128Mi' → 128. 단위는 Mi 만 씁니다."""
    return int(value.rstrip("Mi"))


def deployment(
    tag=GOOD_TAG,
    memory_limit="128Mi",
    readiness_path="/",
    replicas=2,
    warmup_mb=48,
):
    """앱 매니페스트를 만듭니다. 인자를 비틀면 그게 곧 장애 시나리오입니다.

    warmup_mb 는 기동 직후 실제로 메모리를 잡는 초기화 단계입니다.
    실제 서비스의 캐시 워밍업이나 인덱스 로딩을 흉내낸 것입니다.

    이게 없으면 nginx 는 메모리를 거의 안 써서 limit 을 4Mi 로 낮춰도 멀쩡히 돕니다.
    (실제로 확인했습니다) 그래서 "한도를 낮췄더니 죽는다" 를 재현하려면
    한도에 부딪힐 만큼 메모리를 쓰는 동작이 있어야 합니다.

    주의: memory request 는 limit 을 넘을 수 없습니다.
    넘으면 쿠버네티스가 Deployment 자체를 거부하고, 그러면 pod 가 죽는 게 아니라
    **배포가 아예 안 됩니다.** 우리가 보고 싶은 건 OOMKilled 이지 매니페스트 오류가 아니므로
    limit 이 작아지면 request 도 같이 낮춥니다.
    """
    memory_request = f"{min(32, _mi(memory_limit))}Mi"
    return f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {APP}
  namespace: {NAMESPACE}
  labels:
    app: {APP}
spec:
  replicas: {replicas}
  selector:
    matchLabels:
      app: {APP}
  template:
    metadata:
      labels:
        app: {APP}
    spec:
      containers:
        - name: {APP}
          image: {IMAGE_REPO}:{tag}
          # 기동 시 캐시 워밍업 {warmup_mb}MB 후 nginx 실행.
          # 메모리 limit 이 이보다 작으면 여기서 OOMKilled 됩니다.
          command: ["/bin/sh", "-c"]
          args: ["head -c {warmup_mb}M /dev/zero | tail -c {warmup_mb}M > /dev/null; exec nginx -g 'daemon off;'"]
          ports:
            - containerPort: 80
          resources:
            requests:
              cpu: 50m
              memory: {memory_request}
            limits:
              memory: {memory_limit}
          readinessProbe:
            httpGet:
              path: {readiness_path}
              port: 80
            initialDelaySeconds: 3
            periodSeconds: 5
            failureThreshold: 3
          livenessProbe:
            httpGet:
              path: /
              port: 80
            initialDelaySeconds: 10
            periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: {APP}
  namespace: {NAMESPACE}
spec:
  selector:
    app: {APP}
  ports:
    - port: 80
      targetPort: 80
"""


# ---------------------------------------------------------------------------
# 장애 시나리오
# ---------------------------------------------------------------------------
# 각 시나리오는 (커밋 메시지, 매니페스트, 무엇이 실제로 일어나는가) 로 정의됩니다.
# 커밋 메시지는 에이전트가 읽는 유일한 '의도' 정보이므로 현실적으로 씁니다.

SCENARIOS = {
    "healthy": {
        "title": "정상 배포",
        "commit": "chore: 정상 상태로 복구",
        "manifest": lambda: deployment(),
        "expect": "모든 pod Running · Ready. ArgoCD Healthy",
        "hint": "대조군. 에이전트가 '이상 없음'이라고 판단하는지 봅니다.",
    },
    "image-tag": {
        "title": "이미지 태그 오타 → ImagePullBackOff",
        "commit": "release: kdt-dev-api 1.29.0 배포",
        "manifest": lambda: deployment(tag="1.290"),
        "expect": "새 pod 가 ImagePullBackOff. 이벤트에 manifest unknown",
        "hint": "커밋 메시지는 1.29.0 인데 실제 태그는 1.290 입니다. "
                "Git 과 클러스터를 교차 확인해야 보입니다.",
    },
    "oom": {
        "title": "메모리 한도 하향 → OOMKilled",
        "commit": "chore: 비용 절감 위해 메모리 limit 하향 (128Mi → 32Mi)",
        "manifest": lambda: deployment(memory_limit="32Mi"),
        "expect": "pod 가 CrashLoopBackOff. 직전 컨테이너 종료 사유 OOMKilled, exit 137",
        "hint": "기동 시 캐시 워밍업(48MB)이 32Mi 한도를 넘어 죽습니다. "
                "현재 로그는 비어 있고, 직전 컨테이너 상태를 봐야 원인이 나옵니다.",
    },
    "probe": {
        "title": "readiness 경로 변경 → Rollout 정체",
        "commit": "refactor: 헬스체크 경로를 /healthz 로 통일",
        "manifest": lambda: deployment(readiness_path="/healthz"),
        "expect": "pod 는 Running 인데 Ready 가 안 됨. 이벤트에 Readiness probe failed 404",
        "hint": "가장 어렵습니다. 앱 자체는 멀쩡하고 로그도 정상입니다. "
                "probe 설정 변경을 커밋에서 찾아야 합니다.",
    },
    "both": {
        "title": "복합 장애 (태그 오타 + 메모리)",
        "commit": "release: 1.29.0 배포 + 리소스 조정",
        "manifest": lambda: deployment(tag="1.290", memory_limit="32Mi"),
        "expect": "ImagePullBackOff 가 먼저 보이지만 그것만이 아님",
        "hint": "심화용. 에이전트가 첫 번째 원인에서 멈추는지 봅니다.",
    },
}


def argocd_application(repo_url, revision="main"):
    """ArgoCD Application 커스텀 리소스."""
    return {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Application",
        "metadata": {"name": APP, "namespace": "argocd"},
        "spec": {
            "project": "default",
            "source": {
                "repoURL": repo_url,
                "targetRevision": revision,
                "path": "manifests",
            },
            "destination": {
                "server": "https://kubernetes.default.svc",
                "namespace": NAMESPACE,
            },
            "syncPolicy": {
                "automated": {"prune": True, "selfHeal": True},
                "syncOptions": ["CreateNamespace=true"],
                "retry": {"limit": 3, "backoff": {"duration": "10s", "maxDuration": "1m"}},
            },
        },
    }
