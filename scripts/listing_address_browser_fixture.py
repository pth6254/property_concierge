"""가상 주소 검색 응답을 로컬 브라우저 검증 계정에 연결한다. 외부 API 실적이 아니다."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=False)

from tests.legacy_address_token import sign_address
from schemas.listing_address import ListingAddress

owner_id = int(sys.argv[1])
address = ListingAddress(road_address="서울 강남구 테헤란로 123", jibun_address="서울 강남구 역삼동 123",
    legal_region_code="1168010100", latitude=37.5, longitude=127.04, building_name="주소 등록 검증 단지",
    name_source="kakao_address", name_status="found", checked_at=datetime.now(timezone.utc).isoformat(), identity_level="building")
print(json.dumps({"items": [{**address.model_dump(), "token": sign_address(address, owner_id)}]}, ensure_ascii=False))
