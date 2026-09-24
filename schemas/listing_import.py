"""사용자 제공 매물의 수입 계약. CSV도 API와 동일한 원·㎡ 단위를 사용한다."""
from datetime import datetime, timezone, timedelta
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class ListingInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    external_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=150)
    property_type: Literal["apartment", "officetel", "row_house", "detached", "non_residential", "industrial", "land"]
    transaction_type: Literal["purchase", "lease", "rent"]
    address: str = Field(min_length=1, max_length=500)
    legal_region_code: str | None = Field(default=None, pattern=r"^\d{10}$")
    area_sqm: float = Field(gt=0, le=100000000)
    floor: str = Field(default="", max_length=30)
    asking_price: int | None = Field(default=None, gt=0, le=10**15)
    deposit: int | None = Field(default=None, ge=0, le=10**15)
    monthly_rent: int | None = Field(default=None, gt=0, le=10**12)
    source_url: HttpUrl | None = None
    confirmed_at: datetime
    status: Literal["active", "withdrawn", "completed", "unknown"] = "unknown"

    @field_validator("confirmed_at")
    @classmethod
    def confirmed_date(cls, value):
        if value.tzinfo is None:
            raise ValueError("확인 시각에는 시간대(+09:00 등)가 필요합니다")
        if value > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("미래 확인 시각은 사용할 수 없습니다")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def check_prices(self):
        if self.transaction_type == "purchase":
            if self.asking_price is None or self.deposit is not None or self.monthly_rent is not None:
                raise ValueError("매매는 asking_price만 입력해야 합니다")
        elif self.transaction_type == "lease":
            if self.deposit is None or self.deposit <= 0 or self.asking_price is not None or self.monthly_rent is not None:
                raise ValueError("전세는 양수 deposit만 입력해야 합니다")
        elif self.deposit is None or self.monthly_rent is None or self.asking_price is not None:
            raise ValueError("월세는 deposit과 monthly_rent를 입력해야 합니다")
        return self


class ListingImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_name: str = Field(min_length=1, max_length=100)
    csv_text: str = Field(min_length=1, max_length=1_000_000)
    commit: bool = False

    @field_validator("source_name")
    @classmethod
    def source_text(cls, value):
        if "\x00" in value:
            raise ValueError("출처에 허용되지 않는 제어 문자가 있습니다")
        return value
