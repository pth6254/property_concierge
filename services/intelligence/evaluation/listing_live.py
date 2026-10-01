"""사람이 같은 시점에 확인한 개별 매물과 실제 추출값을 대조한다."""
from __future__ import annotations
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.services.naver_listing_collector import canonical_url, collect_page


class ExpectedListing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    url: str
    reviewed_at: datetime
    expected: dict

    @model_validator(mode="after")
    def check(self):
        canonical_url(self.url)
        allowed = {"asking_price", "deposit", "monthly_rent", "area_sqm", "address", "transaction_type", "source_confirmed_date"}
        if not {"area_sqm", "address"}.issubset(self.expected) or not ({"asking_price", "deposit"} & self.expected.keys()):
            raise ValueError("정답에는 전용면적·주소와 호가 또는 보증금이 필요합니다")
        if set(self.expected) - allowed or any(v is None for v in self.expected.values()):
            raise ValueError("지원하지 않거나 비어 있는 정답 필드입니다")
        if self.reviewed_at.tzinfo is None:
            raise ValueError("정답 확인 시각에 시간대가 필요합니다")
        age = (datetime.now(timezone.utc) - self.reviewed_at).total_seconds()
        if age < -60 or age > 86400:
            raise ValueError("24시간 이내에 사람이 확인한 정답을 사용하세요")
        return self


def differences(expected: dict, actual: dict) -> dict:
    result = {}
    for key, value in expected.items():
        observed = actual.get(key)
        same = abs(value-observed) <= .01 if key == "area_sqm" and isinstance(value,(int,float)) and isinstance(observed,(int,float)) else value == observed
        if not same:
            result[key] = {"expected": value, "actual": observed}
    return result


async def evaluate(path: Path, output: Path, max_cases: int) -> dict:
    rows = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(rows,list) or not rows:
        raise ValueError("실제로 확인한 매물 정답 목록이 필요합니다")
    cases = [ExpectedListing.model_validate(row) for row in rows[:max_cases]]
    if len({c.id for c in cases}) != len(cases):
        raise ValueError("사례 ID는 중복될 수 없습니다")
    results = []
    for case in cases:
        observation = await collect_page(case.url)
        diff = differences(case.expected, observation.get("fields", {}))
        results.append({"id": case.id, "reviewed_at": case.reviewed_at.isoformat(),
                        "observation": observation, "differences": diff,
                        "passed": observation["outcome"] == "observed" and not diff})
    report = {"mode": "live", "checked_at": datetime.now(timezone.utc).isoformat(),
              "total": len(results), "passed": sum(r["passed"] for r in results), "results": results,
              "boundary": "페이지 추출값 대조이며 거래 가능 여부·중개사 확인을 보증하지 않습니다. 조회 실패도 분모에 포함합니다."}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return report
