"""구 주소 증명의 Spring 호환성·만료 회귀 자료. 실행 서비스는 사용하지 않는다."""
import base64, hashlib, hmac, json, time
from tests.legacy_auth import SECRET_KEY
from schemas.listing_address import ListingAddress
TOKEN_SECONDS = 3600
def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")

def _signature(body: str) -> str:
    # 인증 JWT와 다른 형식·용도다. 주소 증명으로 로그인 세션을 만들 수 없게 한다.
    return _encode(hmac.new(SECRET_KEY.encode(), b"listing-address-v1:" + body.encode(), hashlib.sha256).digest())

def sign_address(address: ListingAddress, user_id: int) -> str:
    body = _encode(json.dumps({"owner": user_id, "expires": time.time() + TOKEN_SECONDS,
                              "address": address.model_dump()}, ensure_ascii=False, separators=(",", ":")).encode())
    return body + "." + _signature(body)
