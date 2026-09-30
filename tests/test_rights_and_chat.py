"""
test_rights_and_chat.py — 권리 점검·상속증여세·챗봇 단위 테스트
"""

from __future__ import annotations

import os

import pytest


import services.rights_analysis_service as ras
from tax_rules import calc_gift_tax, calc_inheritance_tax

RISKY_REGISTRY = """
[집합건물] 서울특별시 서초구 반포동 123 래미안아파트 제101동 제501호
[갑구] 순위 4 가압류 2025년11월1일 청구금액 금50,000,000원 채권자 하나캐피탈
[을구] 순위 1 근저당권설정 채권최고액 금360,000,000원 근저당권자 국민은행
순위 2 근저당권설정 채권최고액 금120,000,000원
주요 등기사항 요약 (참고용)
1. 소유지분현황 (갑구) 소유자 김철수 단독소유
2. 가압류 금50,000,000원
3. (근)저당권 (을구) 채권최고액 금360,000,000원 / 채권최고액 금120,000,000원
"""

CLEAN_REGISTRY = """
[집합건물] 서울특별시 마포구 아현동 5 마포아파트 제3동 제101호
주요 등기사항 요약
1. 소유지분현황 (갑구) 소유자 박영희
"""


# ─────────────────────────────────────────
#  권리 점검
# ─────────────────────────────────────────

class TestRightsAnalysis:
    def test_parse_risky_registry(self):
        r = ras.parse_registry(RISKY_REGISTRY)
        assert r["address"].startswith("서울특별시 서초구")
        assert r["owner"] == "김철수"
        assert r["mortgage_total"] == 480_000_000
        assert any(c["keyword"] == "가압류" for c in r["critical"])

    def test_parse_empty_text(self):
        assert ras.parse_registry("")["error"]

    def test_deposit_safety_danger(self):
        s = ras.assess_deposit_safety(800_000_000, 480_000_000, 0, 300_000_000, "서울시")
        assert s["grade"] == "danger" and s["burden_ratio"] > 0.9
        assert s["expected_recovery"] == 160_000_000    # 낙찰 6.4억 − 선순위 4.8억

    def test_deposit_safety_safe(self):
        s = ras.assess_deposit_safety(700_000_000, 0, 0, 200_000_000, "서울시")
        assert s["grade"] == "safe"
        assert not s["small_tenant"]                    # 서울 1.65억 초과

    def test_small_tenant(self):
        s = ras.assess_deposit_safety(300_000_000, 0, 0, 100_000_000, "서울특별시")
        assert s["small_tenant"] and s["small_tenant_rule"]["priority_amount"] == 55_000_000

    def test_analyze_integration(self, monkeypatch):
        monkeypatch.setattr(ras, "extract_pdf_text", lambda b: RISKY_REGISTRY)
        res = ras.analyze_rights(registry_pdf=b"%PDF-x",
                                 my_deposit=300_000_000, market_price=800_000_000)
        assert res["risk_grade"] == "danger" and res["risk_score"] >= 60
        monkeypatch.setattr(ras, "extract_pdf_text", lambda b: CLEAN_REGISTRY)
        res = ras.analyze_rights(registry_pdf=b"%PDF-x",
                                 my_deposit=200_000_000, market_price=700_000_000)
        assert res["risk_grade"] == "safe"

    def test_building_violation(self):
        # parse_building_ledger 는 50자 미만 입력을 "텍스트 추출 실패"로 처리하므로
        # (스캔 이미지 PDF 방어) 실제 대장에 준하는 길이의 텍스트를 넘긴다.
        text = (
            "건축물대장 (갑) 위반건축물\n"
            "대지위치: 서울특별시 마포구 신촌동 123-45\n"
            "주용도: 단독주택\n"
            "호수 1\n"
            "사용승인일: 2005.06.30\n"
        )
        r = ras.parse_building_ledger(text)
        assert not r["error"]
        assert r["violation"]


# ─────────────────────────────────────────
#  상속·증여세 골든
# ─────────────────────────────────────────

class TestEstateGiftTax:
    def test_gift_adult_child_5eok(self):
        """성인 자녀 5억: (5억−5천만)→20% 구간 8천만 → 신고공제 3% = 7,760만."""
        r = calc_gift_tax(500_000_000, "직계존속")
        assert r["gross_tax"] == 80_000_000 and r["tax"] == 77_600_000

    def test_gift_spouse_fully_deducted(self):
        assert calc_gift_tax(600_000_000, "배우자")["tax"] == 0

    def test_gift_10yr_aggregation(self):
        """기존 3억 + 이번 3억 (직계존속): 총세 1.05억 − 기존분 4천만 = 6.5천만 → 3% 공제."""
        r = calc_gift_tax(300_000_000, "직계존속", prior_gifts_10yr=300_000_000)
        assert r["gross_tax"] == 65_000_000 and r["tax"] == 63_050_000

    def test_inheritance_10eok_with_spouse_zero(self):
        assert calc_inheritance_tax(1_000_000_000, has_spouse=True)["tax"] == 0

    def test_inheritance_20eok(self):
        """20억 − 공제 10억 = 과세 10억 → 30% − 6천만 = 2.4억 → 3% 공제 = 2.328억."""
        r = calc_inheritance_tax(2_000_000_000, has_spouse=True)
        assert r["gross_tax"] == 240_000_000 and r["tax"] == 232_800_000


# ─────────────────────────────────────────
#  챗봇 (모의 LLM)
# ─────────────────────────────────────────

class _R:
    def __init__(self, c): self.content = c


class _FakeLLM:
    def __init__(self, out): self.out = out
    def invoke(self, _): return _R(self.out)


class TestChatService:
    @pytest.fixture(autouse=True)
    def _corpus_tmp(self, monkeypatch):
        """
        chat_chunks 테이블을 비운 상태로 격리.

        이전에는 DB_PATH(SQLite 파일 경로)를 tmp_path로 monkeypatch해 테스트마다
        별개 파일을 썼다. Postgres 전환 후에는 테이블만 비우고, ensure_corpus()가
        다시 시드 코퍼스를 채우게 한다.
        """
        import chat_corpus

        from db.models import ChatChunk
        from tests.conftest import truncate_tables

        truncate_tables(ChatChunk)
        monkeypatch.setattr(chat_corpus, "_INITIALIZED", False)
        monkeypatch.setattr(chat_corpus, "_try_embed", lambda texts: None)  # 키워드 폴백

    def test_tool_call_with_number_guard(self, monkeypatch):
        import model_factory
        import services.chat_service as cs
        monkeypatch.setattr(model_factory, "get_chat_llm", lambda **kwargs: _FakeLLM(
            '{"tool": "gift_tax", "params": {"gift_value": 500000000, "relation": "직계존속"}}' if kwargs.get("json_mode") else
            "증여세는 약 77,600,000원입니다. 세액은 88,123,456원까지 오를 수 있습니다. 전문가 확인이 필요합니다."))
        out = cs.answer_question("성인 자녀에게 5억 증여하면 증여세?")
        assert out["tool_used"] == "증여세 계산"
        assert "77,600,000" in out["answer"]
        assert "88,123,456" not in out["answer"]     # 위조 수치 차단

    def test_rag_only_question(self, monkeypatch):
        import model_factory
        import services.chat_service as cs
        monkeypatch.setattr(model_factory, "get_chat_llm", lambda **kwargs: _FakeLLM(
            '{"tool": "none", "params": {}}' if kwargs.get("json_mode") else
            "묵시적 갱신 시 임차인은 해지 통지 3개월 후 나갈 수 있습니다. 전문가 확인이 필요합니다."))
        out = cs.answer_question("묵시적 갱신되면 언제 나갈 수 있나요?")
        assert out["tool_used"] is None and out["sources"]

    def test_llm_down_fallback(self, monkeypatch):
        import model_factory
        import services.chat_service as cs
        def boom(**_): raise RuntimeError("down")
        monkeypatch.setattr(model_factory, "get_chat_llm", boom)
        out = cs.answer_question("전세 보증금 못 받으면?")
        assert out["answer"] and out["disclaimer"]

    def test_evaluation_trace_is_opt_in_and_not_exposed_in_response(self, monkeypatch):
        import model_factory
        import services.chat_service as cs
        monkeypatch.setattr(model_factory, "get_chat_llm", lambda **kwargs: _FakeLLM(
            '{"tool":"none","params":{}}' if kwargs.get("json_mode") else "관련 자료를 확인하세요."))
        trace = {}
        output = cs.answer_question("묵시적 갱신", trace=trace)
        assert set(output) == {"answer", "sources", "tool_used", "disclaimer", "blocked"}
        assert trace["raw_answer"] == output["answer"]
        assert trace["retrieval"]["mode"] == "keyword"
        assert trace["retrieval"]["corpus_sha256"]
        assert trace["route"]["tool"] == "none"

    def test_evaluation_trace_marks_llm_failure_even_with_fallback_answer(self, monkeypatch):
        import model_factory
        import services.chat_service as cs
        def boom(**_):
            raise RuntimeError("down")
        monkeypatch.setattr(model_factory, "get_chat_llm", boom)
        trace = {}
        output = cs.answer_question("묵시적 갱신", trace=trace)
        assert output["answer"]
        assert trace["routing_error"] == trace["generation_error"] == "RuntimeError"
        assert trace["fallback"] == "corpus"
