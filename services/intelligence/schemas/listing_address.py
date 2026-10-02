"""주소 조회로 확인한 건물·필지 정보. 광고 상태·개별 호와 구분한다."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ListingAddress(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    road_address: str = Field(default="", max_length=500)
    jibun_address: str = Field(min_length=1, max_length=500)
    legal_region_code: str = Field(pattern=r"^\d{10}$")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    building_name: str = Field(default="", max_length=150)
    name_source: Literal["kakao_address", "building_register", "unknown"]
    name_status: Literal["found", "unknown", "ambiguous"]
    name_candidates: list[str] = Field(default_factory=list, max_length=10)
    source: Literal["kakao_address"] = "kakao_address"
    checked_at: str
    identity_level: Literal["building", "parcel"]
    parcel_main_no: str = Field(default="", pattern=r"^(|[0-9]{1,4})$")
    parcel_sub_no: str = Field(default="", pattern=r"^(|[0-9]{1,4})$")
    parcel_mountain: bool = False


class ListingAddressChoice(ListingAddress):
    token: str
