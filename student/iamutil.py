"""
IAM 주체 ARN 을 EKS access entry 가 받는 형태로 정규화합니다.

EKS 는 "누가 이 클러스터에 접근하는가"를 IAM 주체 ARN 으로 관리합니다.
그런데 사람들이 손에 쥐고 있는 값은 대개 **세션 ARN** 입니다.

    aws sts get-caller-identity 가 주는 것 (세션 ARN — access entry 는 거부합니다)
        arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_Admin_abc/me@corp.com

    access entry 가 원하는 것 (실제 역할 ARN)
        arn:aws:iam::123456789012:role/aws-reserved/sso.amazonaws.com/ap-northeast-2/AWSReservedSSO_Admin_abc
                                       └────────── SSO 역할은 이 경로를 가집니다 ──────────┘

문자열만 조립하면 경로가 빠져서 "invalid principal" 이 납니다.
그래서 역할 이름만 뽑아 IAM 에 실제 ARN 을 물어봅니다.
GetRole 은 경로를 몰라도 이름만으로 찾아줍니다.
"""


def normalize_principal(arn, iam=None):
    """세션 ARN 이면 실제 역할 ARN 으로 바꿔서 돌려줍니다.

    반환값: (정규화된 ARN, 안내 메시지 또는 None)
    """
    arn = (arn or "").strip()
    if not arn:
        return "", None

    if ":assumed-role/" not in arn:
        return arn, None

    role_name = arn.split(":assumed-role/")[1].split("/")[0]
    if iam is not None:
        try:
            real = iam.get_role(RoleName=role_name)["Role"]["Arn"]
            return real, f"세션 ARN 을 실제 역할 ARN 으로 변환했습니다: {real}"
        except Exception as exc:  # noqa: BLE001
            return "", (
                f"역할 '{role_name}' 을 IAM 에서 찾지 못했습니다 ({type(exc).__name__}). "
                "이 값은 건너뜁니다."
            )

    account = arn.split(":")[4]
    return f"arn:aws:iam::{account}:role/{role_name}", None


def looks_valid(arn):
    """access entry 에 넣어도 되는 모양인지 최소한만 봅니다."""
    return bool(arn) and arn.startswith("arn:aws:iam::") and (
        ":role/" in arn or ":user/" in arn
    )
