"""cases 내부 계약 클라이언트. 저장·권한·트랜잭션은 Kotlin에서 처리한다."""
from __future__ import annotations

from typing import Optional
from api.core_bridge import core_store


@core_store("cases")
def create_case(user_id: int, data: dict) -> dict:
    ...

@core_store("cases")
def list_cases(user_id: int) -> list[dict]:
    ...

@core_store("cases")
def get_case(case_id: int, user_id: int) -> dict | None:
    ...

@core_store("cases")
def update_case(case_id: int, user_id: int, data: dict) -> dict | None:
    ...

@core_store("cases")
def delete_case(case_id: int, user_id: int) -> bool:
    ...

@core_store("cases")
def add_property(case_id: int, user_id: int, data: dict) -> dict | None:
    ...

@core_store("cases")
def update_property(case_id: int, property_id: int, user_id: int, data: dict) -> dict | None:
    ...

@core_store("cases")
def apply_listing_update(case_id: int, property_id: int, user_id: int,
                         expected_revision_id: int, expected_confirmed_at: str) -> dict | None:
    ...

@core_store("cases")
def select_final_candidate(case_id: int, property_id: int, user_id: int, reason: str) -> dict | None:
    ...

@core_store("cases")
def clear_final_candidate(case_id: int, user_id: int) -> dict | None:
    ...

@core_store("cases")
def update_checklist(case_id: int, property_id: int, checklist_id: int, user_id: int, data: dict) -> dict | None:
    ...

@core_store("cases")
def validate_candidate(case_id: int, property_id: int, user_id: int) -> bool:
    ...

@core_store("cases")
def candidate_inputs(case_id: int, property_id: int, user_id: int) -> dict | None:
    ...

@core_store("cases")
def link_appraisal(case_id: int, property_id: int, history_id: int, user_id: int, result: dict,
                   expected_inputs: dict | None = None) -> bool:
    ...

@core_store("cases")
def link_candidate_analysis(case_id: int, property_id: int, user_id: int, analysis_type: str,
                            summary: dict, checklist_status: str = "done", evidence: str = "",
                            expected_inputs: dict | None = None) -> bool:
    ...

@core_store("cases")
def delete_property(case_id: int, property_id: int, user_id: int) -> bool | None:
    ...

@core_store("cases")
def add_region(case_id: int, user_id: int, data: dict) -> dict | None:
    ...

@core_store("cases")
def delete_region(case_id: int, region_id: int, user_id: int) -> bool | None:
    ...
