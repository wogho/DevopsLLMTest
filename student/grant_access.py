#!/usr/bin/env python3
"""
클러스터 접근 권한을 다른 IAM 주체에게도 부여합니다.

    python grant_access.py <IAM 주체 ARN>
    python grant_access.py --list          지금 누가 접근 가능한지

왜 필요한가:
    EKS 는 "누가 이 클러스터에 접근할 수 있는가"를 IAM 주체 단위로 관리합니다(access entry).
    스택을 만든 주체(액세스 키 사용자)에게만 권한이 붙어 있으므로,
    콘솔이나 CloudShell 처럼 **다른 주체**로 접속하면 401 이 납니다.

CloudShell 에서 쓰고 싶다면:
    1) CloudShell 에서 내 주체 ARN 을 확인
           aws sts get-caller-identity --query Arn --output text
    2) 그 값을 여기에 넘김 (아래 '주의' 참고)
           python grant_access.py arn:aws:iam::111122223333:role/MyConsoleRole
    3) CloudShell 에서
           aws eks update-kubeconfig --name kdt-devops-lab --region ap-northeast-2
           kubectl get pods -A

주의:
    SSO/역할로 로그인했다면 get-caller-identity 는 세션 ARN 을 보여줍니다.
        arn:aws:sts::111122223333:assumed-role/AWSReservedSSO_Admin_abc/lshye
    access entry 에 넣어야 하는 것은 **역할 ARN** 입니다.
        arn:aws:iam::111122223333:role/AWSReservedSSO_Admin_abc
    이 스크립트가 자동으로 변환해주니 세션 ARN 을 그대로 붙여넣으셔도 됩니다.
"""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

ADMIN_POLICY = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
STACK = os.environ.get("STACK", "kdt-devops-lab")
OK, NG = "\033[92m✅\033[0m", "\033[91m❌\033[0m"


def normalize(arn, iam=None):
    """iamutil 의 정규화를 그대로 씁니다. (설명은 그쪽 파일에 있습니다)"""
    from iamutil import normalize_principal

    result, note = normalize_principal(arn, iam)
    if note:
        print(f"  {note}")
    return result


def resolve_cluster(session):
    """클러스터 이름을 찾습니다.

    .env 의 자동 생성 구간은 배포가 끝까지 성공해야 채워집니다.
    부트스트랩에서 실패하면 클러스터는 있는데 .env 는 비어 있으므로,
    CloudFormation 스택과 실제 클러스터 목록까지 뒤져봅니다.
    """
    if "--cluster" in sys.argv:
        return sys.argv[sys.argv.index("--cluster") + 1]
    if os.getenv("CLUSTER_NAME"):
        return os.getenv("CLUSTER_NAME")
    # 스택 출력에서
    try:
        st = session.client("cloudformation").describe_stacks(StackName=STACK)["Stacks"][0]
        for o in st.get("Outputs", []):
            if o["OutputKey"] == "ClusterName":
                print(f"  (.env 대신 스택 {STACK} 에서 클러스터 이름을 찾았습니다)")
                return o["OutputValue"]
    except Exception:  # noqa: BLE001
        pass
    # 그래도 없으면 계정의 클러스터 목록에서
    try:
        names = session.client("eks").list_clusters()["clusters"]
        if len(names) == 1:
            print(f"  (계정에 클러스터가 하나뿐이라 그것을 사용합니다: {names[0]})")
            return names[0]
        if names:
            print(f"  계정의 클러스터: {', '.join(names)}")
            print("  --cluster <이름> 으로 지정해주세요.")
    except Exception:  # noqa: BLE001
        pass
    return None


def main():
    try:
        import boto3
        from dotenv import load_dotenv
    except ImportError:
        print(f"{NG} pip install -r requirements.txt 를 먼저 실행하세요.")
        return 1

    load_dotenv(HERE / ".env", override=True)

    session = boto3.Session(
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_DEFAULT_REGION"),
    )
    cluster = resolve_cluster(session)
    if not cluster:
        print(f"{NG} 클러스터를 찾지 못했습니다.")
        print("   python deploy_lab.py 로 인프라를 먼저 만드세요.")
        print("   이미 만들었다면:  python grant_access.py <ARN> --cluster <클러스터이름>")
        return 1
    eks = session.client("eks")

    # ── 목록 ───────────────────────────────────────────────────────────
    positional = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--cluster" in sys.argv:
        idx = sys.argv.index("--cluster") + 1
        if idx < len(sys.argv) and sys.argv[idx] in positional:
            positional.remove(sys.argv[idx])

    if "--list" in sys.argv or not positional:
        print(f"\n  클러스터 {cluster} 에 접근 가능한 주체\n")
        for arn in eks.list_access_entries(clusterName=cluster)["accessEntries"]:
            pols = eks.list_associated_access_policies(
                clusterName=cluster, principalArn=arn
            )["associatedAccessPolicies"]
            names = ", ".join(p["policyArn"].split("/")[-1] for p in pols) or "(정책 없음)"
            print(f"    {arn}")
            print(f"      → {names}")
        print("\n  추가하려면:  python grant_access.py <IAM 주체 ARN>\n")
        return 0

    principal = normalize(positional[0], session.client("iam"))
    if not principal.startswith("arn:aws:iam::"):
        print(f"{NG} IAM 주체 ARN 이어야 합니다: {principal}")
        return 1

    print(f"\n  클러스터 : {cluster}")
    print(f"  주체     : {principal}")

    try:
        eks.create_access_entry(clusterName=cluster, principalArn=principal, type="STANDARD")
        print(f"{OK} access entry 생성")
    except eks.exceptions.ResourceInUseException:
        print("  access entry 가 이미 있습니다. 정책만 확인합니다.")
    except Exception as e:  # noqa: BLE001
        print(f"{NG} 생성 실패: {type(e).__name__}: {str(e)[:250]}")
        if "invalid principal" in str(e):
            print()
            print("   그 ARN 의 주체가 실제로 존재하지 않습니다. 흔한 원인:")
            print("   · SSO 역할인데 경로(path)가 빠졌습니다.")
            print("     정확한 ARN 은 아래로 확인할 수 있습니다:")
            print(f"       aws iam get-role --role-name <역할이름> --query Role.Arn --output text")
            print("   · 다른 계정의 주체입니다.")
        return 1

    try:
        eks.associate_access_policy(
            clusterName=cluster,
            principalArn=principal,
            policyArn=ADMIN_POLICY,
            accessScope={"type": "cluster"},
        )
        print(f"{OK} 클러스터 관리자 권한 부여")
    except Exception as e:  # noqa: BLE001
        print(f"{NG} 정책 연결 실패: {type(e).__name__}: {str(e)[:200]}")
        return 1

    region = os.getenv("AWS_DEFAULT_REGION")
    print("\n  이제 그 주체로 아래를 실행하면 접속됩니다:\n")
    print(f"    aws eks update-kubeconfig --name {cluster} --region {region}")
    print("    kubectl get pods -A\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
