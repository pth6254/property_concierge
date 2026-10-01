"""매수 의사결정 상태·의도·가격 평가의 입력 계약."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from pydantic import Field, model_validator
from evaluation.schema import StrictModel


class AnalysisState(StrictModel):
    analysis_type: Literal["appraisal", "simulation", "rights"]
    analyzed_at: datetime
    expires_at: datetime | None = None
    status: Literal["completed", "pending", "failed"] = "completed"
    summary: dict = Field(default_factory=dict)


class ChecklistState(StrictModel):
    id: int = Field(gt=0)
    category: Literal["price", "funding", "rights", "site", "contract"]
    title: str
    status: Literal["todo", "done", "warning", "blocked"]
    evidence: str = ""


class CandidateState(StrictModel):
    id: int = Field(gt=0)
    name: str
    asking_price: int | None = Field(default=None, ge=0)
    status: Literal["reviewing", "shortlisted", "rejected", "selected"] = "reviewing"
    source: Literal["manual", "recommendation", "appraisal"] | None = None
    source_listing_id: int | None = Field(default=None, gt=0)
    source_status: dict | None = None
    analyses: list[AnalysisState] = Field(default_factory=list)
    checklist: list[ChecklistState] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_records(self):
        kinds = [a.analysis_type for a in self.analyses]
        checks = [c.id for c in self.checklist]
        if len(kinds) != len(set(kinds)) or len(checks) != len(set(checks)):
            raise ValueError("분석 종류·체크리스트 ID는 후보 내에서 중복될 수 없습니다")
        return self


class TaskState(StrictModel):
    template_key: str
    status: Literal["scheduled", "in_progress", "waiting_external", "done", "problem", "not_applicable"]


class DecisionExpectation(StrictModel):
    ready_ids: list[int]
    required_actions: dict[str, list[str]] = Field(default_factory=dict)
    forbidden_actions: dict[str, list[str]] = Field(default_factory=dict)
    first_actions: dict[str, str] = Field(default_factory=dict)
    comparison_values: dict[str, dict] = Field(default_factory=dict)
    execution_summary: dict = Field(default_factory=dict)
    due_dates: dict[str, str | None] = Field(default_factory=dict)


class DecisionStep(StrictModel):
    name: str
    as_of: datetime
    budget_max_won: int | None = Field(default=None, ge=0)
    candidates: list[CandidateState] = Field(min_length=1)
    selected_property_id: int | None = None
    contract_date: date | None = None
    closing_date: date | None = None
    execution_tasks: list[TaskState] = Field(default_factory=list)
    expected: DecisionExpectation

    @model_validator(mode="after")
    def validate_links(self):
        ids = [c.id for c in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("후보 ID 중복")
        if self.selected_property_id is not None and self.selected_property_id not in ids:
            raise ValueError("최종 선택 후보가 입력에 없습니다")
        exp = self.expected
        checked_ids = set(exp.required_actions) | set(exp.forbidden_actions) | set(exp.first_actions) | set(exp.comparison_values)
        if not checked_ids <= {str(i) for i in ids} or not set(exp.ready_ids) <= set(ids):
            raise ValueError("기대 결과가 없는 후보를 참조합니다")
        if self.contract_date and self.closing_date and self.contract_date > self.closing_date:
            raise ValueError("계약·잔금 일정 순서 오류")
        if self.as_of.tzinfo or any(a.analyzed_at.tzinfo or (a.expires_at and a.expires_at.tzinfo) for c in self.candidates for a in c.analyses):
            raise ValueError("서비스 비교와 동일하게 시간대 없는 고정 시각을 사용하세요")
        task_keys = [t.template_key for t in self.execution_tasks]
        if len(task_keys) != len(set(task_keys)):
            raise ValueError("실행 작업 중복")
        return self


class DecisionCase(StrictModel):
    id: str
    rationale: str = Field(min_length=1)
    steps: list[DecisionStep] = Field(min_length=1)


class IntentTurn(StrictModel):
    message: str = Field(min_length=1)
    expected_intent: Literal["find_region", "select_property", "appraise", "compare", "simulate", "rights_check", "tax_legal", "general"]
    expected_criteria: dict = Field(default_factory=dict)


class IntentCase(StrictModel):
    id: str
    turns: list[IntentTurn] = Field(min_length=1)


class AvmDeal(StrictModel):
    apt_name: str
    dong: str
    area_sqm: float = Field(gt=0)
    price_manwon: int = Field(gt=0)


class AvmCase(StrictModel):
    id: str
    region_name: str
    lawd_cd: str = Field(pattern=r"^\d{5}$")
    target_months: int = Field(default=1, ge=1, le=12)
    window: int = Field(default=6, ge=1, le=60)
    months: dict[str, list[AvmDeal]] = Field(min_length=3)
    min_samples: int = Field(default=1, ge=1)
    min_coverage: float = Field(default=1, ge=0, le=1)
    max_mape: float = Field(default=0.2, ge=0)

    @model_validator(mode="after")
    def validate_months(self):
        for month in self.months:
            if len(month) != 6:
                raise ValueError("거래 월은 YYYYMM 형식입니다")
            datetime.strptime(month, "%Y%m")
        return self
