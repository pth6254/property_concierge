"""평가 데이터 오타가 조용히 무시되지 않도록 엄격한 스키마를 사용한다."""
from __future__ import annotations

import math
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Check(StrictModel):
    name: str
    passed: bool
    expected: object = None
    actual: object = None


class Reference(StrictModel):
    basis: Literal["repository_regression", "manual_calculation", "official_reference"]
    source: str = Field(min_length=1)
    as_of: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    explanation: str = Field(min_length=1)
    independently_verified: bool = False


class CalculatorCase(StrictModel):
    id: str = Field(min_length=1)
    function: Literal["calc_gift_tax", "calc_inheritance_tax", "calc_capital_gains_tax",
                      "calc_annual_holding_tax", "check_dsr", "check_ltv", "estimate_official_price"]
    inputs: dict
    expected: dict = Field(min_length=1)
    tolerance: float = Field(default=0, ge=0)
    reference: Reference


class LawArticleReference(StrictModel):
    law_id: str = Field(pattern=r"^\d{6}$")
    article: str = Field(min_length=1)


class RagCase(StrictModel):
    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    relevant_titles: list[str] = Field(default_factory=list)
    relevant_articles: list[LawArticleReference] = Field(default_factory=list)
    retrieval_backend: Literal["service", "chat_corpus"] = "service"
    reference: Reference | None = None
    require_official_law: bool = False
    expect_no_results: bool = False
    min_recall: float = Field(default=1, ge=0, le=1)

    @model_validator(mode="after")
    def require_judgment(self):
        if bool(self.relevant_titles or self.relevant_articles) == self.expect_no_results:
            raise ValueError("정답 문서 또는 검색 결과 없음 중 하나를 지정하세요")
        if self.relevant_titles and self.relevant_articles:
            raise ValueError("조문 ID 정답과 제목 정답을 함께 지정하지 마세요")
        return self


class ChatTurn(StrictModel):
    question: str = Field(min_length=1, max_length=2000)
    expected_tool: Literal["none", "gift_tax", "inheritance_tax", "capital_gains_tax", "holding_tax"]
    expected_params: dict = Field(default_factory=dict)
    expected_outputs: dict = Field(default_factory=dict)
    answer_required_numbers: list[float] = Field(default_factory=list)
    relevant_titles: list[str] = Field(default_factory=list)
    answer_contains_any: list[str] = Field(default_factory=list)
    answer_forbids: list[str] = Field(default_factory=list)
    allow_fallback: bool = False
    review_focus: str = Field(min_length=1)


class ChatCase(StrictModel):
    id: str = Field(min_length=1)
    turns: list[ChatTurn] = Field(min_length=1, max_length=10)


class Dataset(StrictModel):
    version: str = Field(min_length=1)
    suite: Literal["decision", "avm", "intent", "calculator", "rag", "chat"]
    cases: list[dict] = Field(min_length=1)

    def validated_cases(self):
        from evaluation.decision_schema import DecisionCase, AvmCase, IntentCase
        model = {"calculator": CalculatorCase, "rag": RagCase, "chat": ChatCase,
                 "decision": DecisionCase, "avm": AvmCase, "intent": IntentCase}[self.suite]
        cases = [model.model_validate(case) for case in self.cases]
        ids = [case.id for case in cases]
        if len(ids) != len(set(ids)):
            raise ValueError("평가 사례 ID는 중복될 수 없습니다")
        return cases


def equals(expected, actual, tolerance=0):
    # bool은 int의 하위 유형이지만 세금 1원과 True를 같은 결과로 판정하면 안 된다.
    if isinstance(expected, bool):
        return isinstance(actual, bool) and actual == expected
    if isinstance(expected, (int, float)):
        return (isinstance(actual, (int, float)) and not isinstance(actual, bool)
                and math.isfinite(actual) and abs(expected - actual) <= tolerance)
    return type(expected) is type(actual) and expected == actual


def expected_checks(expected: dict, actual: dict, prefix: str, tolerance=0) -> list[dict]:
    return [Check(name=f"{prefix}.{key}", passed=key in actual and equals(value, actual[key], tolerance),
                  expected=value, actual=actual.get(key)).model_dump() for key, value in expected.items()]
