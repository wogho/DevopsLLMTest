#!/usr/bin/env python3
"""ArgoCD 초기 admin 비밀번호를 알려줍니다.  python argocd_password.py"""

import base64
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
from k8s import Cluster  # noqa: E402

c = Cluster()
sec = c.get("/api/v1/namespaces/argocd/secrets/argocd-initial-admin-secret")
print("\n  ArgoCD")
print(f"    URL      https://{c.service_host('argocd', 'argocd-server')}")
print("    사용자    admin")
print(f"    비밀번호  {base64.b64decode(sec['data']['password']).decode()}\n")
print("  (자체 서명 인증서라 브라우저 경고가 뜹니다. 계속 진행하시면 됩니다.)\n")
