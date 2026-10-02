"""조회 시점·원거래·페이지·최소 발췌와 실패 상태가 근거에 보존되는지 검증한다."""
from backend.transaction_evidence import attach_transaction_evidence
from backend.services.case_snapshot_presentation import _appraisal_evidence
from backend.services.rights_analysis_service import analyze_rights, document_evidence, parse_registry, match_document_subject
from tests.test_rights_and_chat import CLEAN_REGISTRY, RISKY_REGISTRY


def test_transaction_evidence_survives_appraisal_summary():
    rows = [{"apt_name": "검증 단지", "apt_name_matched": "검증 단지", "dong": "반포동", "area_sqm": 84.0,
             "target_area_sqm": 85.0, "price": 80000, "original_price": 78000, "per_sqm": 952,
             "floor": "5", "deal_year": "2025", "deal_month": "3", "deal_day": "9"}]
    attach_transaction_evidence(rows, "RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev", "11650", "202503", 1700000000)
    result = _appraisal_evidence({"analysis_result": {"comparable_count": 1, "comparables": rows}})
    comp = result["comparables"][0]
    assert comp["deal_date"] == "2025-03-09" and comp["original_price"] == 780000000
    assert comp["transaction_ref"].startswith("molit-sha256:") and comp["observed_at"]
    assert comp["area_difference_m2"] == 1.0 and comp["selection_reason"]


def test_transaction_fingerprint_is_stable_across_query_times():
    sample = {"apt_name": "검증 단지", "area_sqm": 84.0, "price": 80000}
    first = attach_transaction_evidence([dict(sample)], "endpoint", "11650", "202503", 1700000000)[0]
    second = attach_transaction_evidence([dict(sample)], "endpoint", "11650", "202503", 1700001000)[0]
    assert first["transaction_ref"] == second["transaction_ref"]
    assert first["observed_at"] != second["observed_at"]


def test_registry_evidence_keeps_page_date_and_minimum_quote(monkeypatch):
    text = "발급일자: 2026.10.02\n" + CLEAN_REGISTRY + "\f주요 등기사항 요약\n가압류 채권자 홍길동 주민번호 900101-1234567\n채권최고액 금50,000,000원"
    monkeypatch.setattr("backend.services.rights_analysis_service.extract_pdf_text", lambda raw: text)
    result = analyze_rights(registry_pdf=b"document-bytes")
    assert result["risk_grade"] == "danger"
    entries = [entry for entry in result["evidence"] if entry["item"] == "가압류"]
    assert entries[0]["page"] == 2 and entries[0]["issued_at"] == "2026-10-02"
    assert entries[0]["excerpt"] == "가압류"
    assert all("홍길동" not in entry["excerpt"] and "900101" not in entry["excerpt"] for entry in result["evidence"])
    assert "document-bytes" not in str(result["document_metadata"])


def test_unreadable_page_prevents_full_confirmation(monkeypatch):
    monkeypatch.setattr("backend.services.rights_analysis_service.extract_pdf_text", lambda raw: CLEAN_REGISTRY + "\f")
    result = analyze_rights(registry_pdf=b"document")
    assert result["analysis_status"] == "partial" and result["risk_grade"] == "unknown"
    assert result["document_metadata"]["registry"]["unreadable_pages"] == [2]


def test_unrelated_text_is_not_a_clean_registry():
    assert parse_registry("이 문서는 등기부가 아닌 긴 일반 안내문입니다. " * 10)["error"]


def test_unknown_issue_date_is_not_filled_from_analysis_time():
    meta = document_evidence(RISKY_REGISTRY, "registry", b"document")
    assert meta["issued_at"] is None and all(entry["issued_at"] is None for entry in meta["evidence"])


def test_document_subject_does_not_match_other_unit_or_similar_lot():
    registry = {"address": "서울특별시 강남구 역삼동 123 제101동 제501호"}
    expected = {"address": "서울 강남구 역삼동 123", "identity": {"building_dong": "101", "unit_number": "501"}}
    assert match_document_subject(registry, expected)["status"] == "unit_match"
    assert match_document_subject(registry, {**expected, "identity": {"unit_number": "502"}})["status"] == "mismatch"
    assert match_document_subject({"address": "서울 강남구 역삼동 1234 제501호"}, expected)["status"] == "mismatch"
