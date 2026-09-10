"""
클러스터 안에 올라간 Git 서버와 통신합니다.

Gitea 와 GitLab 은 API 모양이 다르지만, 에이전트가 필요로 하는 것은 네 가지뿐입니다.

    ensure_repo()      리포지토리 준비
    put_file()         파일 쓰기 (= 커밋)
    get_file()         파일 읽기
    recent_commits()   최근 변경 이력

그래서 이 네 개만 같은 이름으로 맞춰두고, 안에서 각자의 API 를 부릅니다.
사내 GitLab 으로 옮길 때는 GitLabClient 의 base_url 과 토큰만 바꾸면 됩니다.
"""

import base64
import os

import requests

TIMEOUT = 30
REPO = "kdt-dev-argo"       # 앱 매니페스트가 사는 리포지토리
BRANCH = "main"


class GiteaClient:
    """Gitea. 기본값이고, 1분이면 뜹니다."""

    kind = "gitea"

    def __init__(self, base_url, user, password):
        self.base = base_url.rstrip("/")
        self.api = f"{self.base}/api/v1"
        self.auth = (user, password)
        self.user = user

    def _r(self, method, path, **kw):
        r = requests.request(
            method, self.api + path, auth=self.auth, timeout=TIMEOUT, **kw
        )
        return r

    def ensure_repo(self):
        r = self._r("GET", f"/repos/{self.user}/{REPO}")
        if r.status_code == 200:
            return False
        r = self._r(
            "POST",
            "/user/repos",
            json={"name": REPO, "auto_init": True, "default_branch": BRANCH,
                  "description": "kdt-dev-api 배포 매니페스트"},
        )
        r.raise_for_status()
        return True

    def get_file(self, path):
        r = self._r("GET", f"/repos/{self.user}/{REPO}/contents/{path}?ref={BRANCH}")
        if r.status_code == 404:
            return None, None
        r.raise_for_status()
        d = r.json()
        return base64.b64decode(d["content"]).decode("utf-8"), d["sha"]

    def put_file(self, path, content, message):
        _, sha = self.get_file(path)
        body = {
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "message": message,
            "branch": BRANCH,
        }
        if sha:
            body["sha"] = sha
            r = self._r("PUT", f"/repos/{self.user}/{REPO}/contents/{path}", json=body)
        else:
            r = self._r("POST", f"/repos/{self.user}/{REPO}/contents/{path}", json=body)
        r.raise_for_status()
        return r.json()["commit"]["sha"][:8]

    def recent_commits(self, limit=5):
        r = self._r("GET", f"/repos/{self.user}/{REPO}/commits?limit={limit}&sha={BRANCH}")
        r.raise_for_status()
        out = []
        for c in r.json()[:limit]:
            out.append(
                {
                    "sha": c["sha"][:8],
                    "message": c["commit"]["message"].strip(),
                    "author": c["commit"]["author"]["name"],
                    "date": c["commit"]["author"]["date"],
                    "url": c.get("html_url", ""),
                }
            )
        return out

    def clone_url(self, internal=True):
        """ArgoCD 가 쓸 주소. 클러스터 안에서는 서비스 DNS 로 붙습니다."""
        if internal:
            # gitea-http 는 headless 라 DNS 가 파드 IP 로 풀립니다.
            # gitea-lb 는 ClusterIP 를 가지므로 ArgoCD 가 붙기에 더 안정적입니다.
            return f"http://gitea-lb.git.svc.cluster.local:3000/{self.user}/{REPO}.git"
        return f"{self.base}/{self.user}/{REPO}.git"


class GitLabClient:
    """GitLab CE. 진짜 GitLab API 를 쓰고 싶을 때."""

    kind = "gitlab"

    def __init__(self, base_url, token, user="root"):
        self.base = base_url.rstrip("/")
        self.api = f"{self.base}/api/v4"
        self.headers = {"PRIVATE-TOKEN": token}
        self.user = user
        self._pid = None

    def _r(self, method, path, **kw):
        return requests.request(
            method, self.api + path, headers=self.headers, timeout=TIMEOUT, **kw
        )

    @property
    def project_id(self):
        if self._pid is None:
            r = self._r("GET", f"/projects/{self.user}%2F{REPO}")
            r.raise_for_status()
            self._pid = r.json()["id"]
        return self._pid

    def ensure_repo(self):
        r = self._r("GET", f"/projects/{self.user}%2F{REPO}")
        if r.status_code == 200:
            self._pid = r.json()["id"]
            return False
        r = self._r(
            "POST",
            "/projects",
            json={"name": REPO, "initialize_with_readme": True,
                  "default_branch": BRANCH, "visibility": "internal"},
        )
        r.raise_for_status()
        self._pid = r.json()["id"]
        return True

    def get_file(self, path):
        p = requests.utils.quote(path, safe="")
        r = self._r("GET", f"/projects/{self.project_id}/repository/files/{p}?ref={BRANCH}")
        if r.status_code == 404:
            return None, None
        r.raise_for_status()
        d = r.json()
        return base64.b64decode(d["content"]).decode("utf-8"), d["blob_id"]

    def put_file(self, path, content, message):
        p = requests.utils.quote(path, safe="")
        existing, _ = self.get_file(path)
        body = {"branch": BRANCH, "content": content, "commit_message": message}
        method = "PUT" if existing is not None else "POST"
        r = self._r(method, f"/projects/{self.project_id}/repository/files/{p}", json=body)
        r.raise_for_status()
        commits = self.recent_commits(1)
        return commits[0]["sha"] if commits else "?"

    def recent_commits(self, limit=5):
        r = self._r(
            "GET", f"/projects/{self.project_id}/repository/commits?ref_name={BRANCH}&per_page={limit}"
        )
        r.raise_for_status()
        return [
            {
                "sha": c["short_id"],
                "message": c["title"],
                "author": c["author_name"],
                "date": c["committed_date"],
                "url": c.get("web_url", ""),
            }
            for c in r.json()[:limit]
        ]

    def clone_url(self, internal=True):
        if internal:
            return f"http://gitlab-webservice-default.git.svc.cluster.local:8181/{self.user}/{REPO}.git"
        return f"{self.base}/{self.user}/{REPO}.git"


# ---------------------------------------------------------------------------
def from_env():
    """.env 값으로 알맞은 클라이언트를 만듭니다."""
    provider = os.getenv("GIT_PROVIDER", "gitea")
    base = os.getenv("GIT_BASE_URL", "")
    if not base:
        raise RuntimeError("GIT_BASE_URL 이 비어 있습니다. python deploy_lab.py 를 먼저 실행하세요.")
    if provider == "gitea":
        return GiteaClient(base, os.getenv("GIT_USER", "labadmin"), os.getenv("GIT_PASSWORD", ""))
    return GitLabClient(base, os.getenv("GIT_TOKEN", ""), os.getenv("GIT_USER", "root"))
