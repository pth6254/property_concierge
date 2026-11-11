"""변화 알림 조건 계산의 내부 계약. 저장·읽음 처리는 Spring이 한다."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class NotificationListing(BaseModel):
    """재확인 대상 판단에 필요한 매물 사실만 받는다. 원문 URL·주소는 받지 않는다."""
    model_config = ConfigDict(extra="forbid")
    id: int = Field(gt=0)
    name: str = Field(default="", max_length=200)
    alias: str = Field(default="", max_length=200)
    status: str = Field(max_length=20)
    confirmed_at: str | None = Field(default=None, max_length=40)
    needs_confirmation: bool
    last_collection_at: float | None = None


class NotificationConditionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Spring이 소유자를 확인한 보관 전 케이스의 저장 스냅샷(decision/decorate와 같은 형식)
    snapshots: list[dict] = Field(default_factory=list, max_length=100)
    listings: list[NotificationListing] = Field(default_factory=list, max_length=5000)
    now: float = Field(gt=0)


class NotificationCondition(BaseModel):
    kind: Literal["analysis_expired", "source_changed", "listing_reconfirm", "trade_update"]
    subject_key: str
    fingerprint: str
    title: str
    body: str
    link: str
    case_id: int | None = None
    property_id: int | None = None
    listing_id: int | None = None


class NotificationConditionResponse(BaseModel):
    conditions: list[NotificationCondition]
    # 실거래 알림 대상이 될 수 있는 후보. 여기에 없는 후보의 열린 실거래 알림은 Spring이 해결 처리한다.
    trade_subjects: list[str]
