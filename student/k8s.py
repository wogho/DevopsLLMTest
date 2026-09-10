"""
Kubernetes API 클라이언트.

kubectl 도 kubeconfig 도 쓰지 않습니다. boto3 자격증명으로 EKS 인증 토큰을 만들어
클러스터 API 서버를 HTTP 로 직접 호출합니다.

왜 이렇게 하는가:
  에이전트가 실제로 하는 일은 "HTTP 요청을 보내고 JSON 을 받는 것"뿐입니다.
  kubectl 을 subprocess 로 부르면 그 사실이 가려집니다.
  도구가 무엇을 하는지 코드에서 그대로 보이는 편이 배우기에도 좋고,
  나중에 사내 환경으로 옮길 때도 인증 부분만 바꾸면 됩니다.

EKS 토큰 방식:
  STS GetCallerIdentity 를 presign 한 URL 을 base64 로 인코딩해서
  'k8s-aws-v1.' 접두사를 붙이면 그게 곧 Bearer 토큰입니다.
  클러스터는 그 URL 을 호출해 누구인지 확인합니다. (유효기간 약 15분)
"""

import base64
import os
import tempfile
import time

import boto3
import requests
from botocore.signers import RequestSigner

TOKEN_TTL = 600  # 초. 만료 전에 새로 만듭니다.


class Cluster:
    """EKS 클러스터 하나에 대한 얇은 REST 클라이언트."""

    def __init__(self, cluster_name=None, session=None):
        self.name = cluster_name or os.environ["CLUSTER_NAME"]
        self.session = session or boto3.Session(
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_DEFAULT_REGION"),
        )
        info = self.session.client("eks").describe_cluster(name=self.name)["cluster"]
        self.endpoint = info["endpoint"]

        # 클러스터 CA 인증서를 임시 파일로 떨궈 TLS 검증에 씁니다
        ca = base64.b64decode(info["certificateAuthority"]["data"])
        fd, self.ca_path = tempfile.mkstemp(prefix="eks-ca-", suffix=".crt")
        with os.fdopen(fd, "wb") as f:
            f.write(ca)

        self._token = None
        self._token_at = 0

    # -----------------------------------------------------------------
    def token(self):
        if self._token and time.time() - self._token_at < TOKEN_TTL:
            return self._token

        region = self.session.region_name
        sts = self.session.client("sts", region_name=region)
        signer = RequestSigner(
            sts.meta.service_model.service_id,
            region,
            "sts",
            "v4",
            self.session.get_credentials(),
            self.session.events,
        )
        url = signer.generate_presigned_url(
            {
                "method": "GET",
                "url": f"https://sts.{region}.amazonaws.com/"
                       f"?Action=GetCallerIdentity&Version=2011-06-15",
                "body": {},
                "headers": {"x-k8s-aws-id": self.name},
                "context": {},
            },
            region_name=region,
            expires_in=900,
            operation_name="",
        )
        self._token = "k8s-aws-v1." + base64.urlsafe_b64encode(
            url.encode("utf-8")
        ).decode("utf-8").rstrip("=")
        self._token_at = time.time()
        return self._token

    # -----------------------------------------------------------------
    def _request(self, method, path, **kw):
        r = requests.request(
            method,
            self.endpoint.rstrip("/") + path,
            headers={
                "Authorization": f"Bearer {self.token()}",
                "Accept": "application/json",
                **kw.pop("headers", {}),
            },
            verify=self.ca_path,
            timeout=kw.pop("timeout", 30),
            **kw,
        )
        return r

    def get(self, path, **kw):
        r = self._request("GET", path, **kw)
        r.raise_for_status()
        return r.json()

    def get_text(self, path, **kw):
        r = self._request("GET", path, headers={"Accept": "text/plain"}, **kw)
        r.raise_for_status()
        return r.text

    def apply(self, path, body):
        """서버사이드 어플라이. 있으면 갱신, 없으면 생성합니다."""
        r = self._request(
            "PATCH",
            path + "?fieldManager=kdt-lab&force=true",
            headers={"Content-Type": "application/apply-patch+yaml"},
            data=body.encode("utf-8") if isinstance(body, str) else body,
        )
        r.raise_for_status()
        return r.json()

    def patch(self, path, body):
        """머지 패치. 어노테이션이나 필드 일부만 바꿀 때 씁니다."""
        r = self._request(
            "PATCH",
            path,
            headers={"Content-Type": "application/merge-patch+json"},
            data=body.encode("utf-8") if isinstance(body, str) else body,
        )
        r.raise_for_status()
        return r.json()

    def delete(self, path):
        r = self._request("DELETE", path)
        if r.status_code not in (200, 202, 404):
            r.raise_for_status()
        return r.status_code

    # ── 자주 쓰는 조회 ────────────────────────────────────────────────
    def pods(self, namespace):
        return self.get(f"/api/v1/namespaces/{namespace}/pods")["items"]

    def pod_logs(self, namespace, pod, tail=60, previous=False, container=None):
        q = f"?tailLines={tail}"
        if previous:
            q += "&previous=true"
        if container:
            q += f"&container={container}"
        return self.get_text(f"/api/v1/namespaces/{namespace}/pods/{pod}/log{q}")

    def events(self, namespace, limit=40):
        items = self.get(f"/api/v1/namespaces/{namespace}/events?limit={limit}")["items"]
        return sorted(items, key=lambda e: e.get("lastTimestamp") or "", reverse=True)

    def argo_app(self, name, namespace="argocd"):
        return self.get(
            f"/apis/argoproj.io/v1alpha1/namespaces/{namespace}/applications/{name}"
        )

    def configmap(self, namespace, name):
        return self.get(f"/api/v1/namespaces/{namespace}/configmaps/{name}").get("data", {})

    def service_host(self, namespace, name):
        svc = self.get(f"/api/v1/namespaces/{namespace}/services/{name}")
        ing = svc.get("status", {}).get("loadBalancer", {}).get("ingress", [])
        if not ing:
            return None
        return ing[0].get("hostname") or ing[0].get("ip")
