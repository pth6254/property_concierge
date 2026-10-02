package kr.propertyconcierge.core.store

import kr.propertyconcierge.core.integration.PlatformIntegrationSupport
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired

class CasePersistenceIT : PlatformIntegrationSupport() {
    @Autowired lateinit var store: CaseStore
    @Test fun `예산 부분 수정 실패는 이전 조건을 보존한다`() {
        val (_, cookie) = register(); val id = case(cookie, mapOf("budget_min" to 500_000_000, "budget_max" to 800_000_000))
        request("PATCH", "/api/cases/$id", mapOf("budget_min" to 900_000_000), cookie, 422)
        val saved = body(request("GET", "/api/cases", cookie=cookie)).path("items").single()
        assertEquals(500_000_000L, saved.path("budget_min").asLong()); assertEquals(800_000_000L, saved.path("budget_max").asLong())
    }
    @Test fun `타인의 케이스 후보 선택과 거래 준비는 조회 변경 모두 차단한다`() {
        val (_, cookie) = register(); val id = case(cookie); val property = candidate(cookie, id)
        val (_, other) = register()
        request("GET", "/api/cases/$id", cookie=other, expected=404)
        request("PATCH", "/api/cases/$id", mapOf("title" to "타인 수정"), other, 404)
        request("PATCH", "/api/cases/$id/properties/$property", mapOf("notes" to "타인 수정"), other, 404)
        request("POST", "/api/cases/$id/decision", mapOf("property_id" to property, "reason" to "타인의 후보 선택"), other, 404)
        request("GET", "/api/cases/$id/execution", cookie=other, expected=404)
        request("DELETE", "/api/cases/$id", cookie=other, expected=404)
        assertEquals(1L, count("purchase_cases")); assertEquals(1L, count("case_properties"))
    }
    @Test fun `후보 선택은 근거를 요구하고 변경과 해제는 저장 상태에 반영된다`() {
        val (_, cookie) = register(); val id = case(cookie); val first = candidate(cookie, id); val second = candidate(cookie, id)
        request("POST", "/api/cases/$id/decision", mapOf("property_id" to first, "reason" to ""), cookie, 422)
        request("POST", "/api/cases/$id/decision", mapOf("property_id" to first, "reason" to "예산 조건을 직접 확인함"), cookie)
        request("DELETE", "/api/cases/$id/properties/$first", cookie=cookie, expected=422)
        request("POST", "/api/cases/$id/decision", mapOf("property_id" to second, "reason" to "임장 결과를 확인함"), cookie)
        assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM case_properties WHERE status='selected'", Int::class.java))
        assertEquals(second, jdbc.queryForObject("SELECT selected_property_id FROM purchase_cases WHERE id=?", Long::class.java, id))
        request("DELETE", "/api/cases/$id/decision", cookie=cookie)
        assertNull(jdbc.queryForList("SELECT selected_property_id FROM purchase_cases WHERE id=?", id).single()["selected_property_id"])
    }
    @Test fun `동호 변경은 분석 선택과 실행 상태를 무효화하고 이전 근거를 보존한다`() {
        val (owner, cookie) = register(); val id = case(cookie)
        val property = candidate(cookie, id, mapOf("identity" to mapOf("building_dong" to "101", "unit_number" to "501", "area_basis" to "exclusive")))
        // 실제 저장 계약으로 분석을 연결한다. 분석 품질은 Python 영역에서 따로 검증한다.
        val analysis = mapOf("user_id" to owner, "case_id" to id, "property_id" to property, "analysis_type" to "rights", "summary" to mapOf("risk_grade" to "unknown"))
        assertEquals(true, store.dispatch("link_candidate_analysis", json.valueToTree(analysis)))
        request("POST", "/api/cases/$id/decision", mapOf("property_id" to property, "reason" to "확인 필요 항목을 알고 선택함"), cookie)
        val task = body(request("GET", "/api/cases/$id/execution", cookie=cookie)).path("tasks").first().path("id").asLong()
        request("PATCH", "/api/cases/$id/execution/tasks/$task", mapOf("status" to "done", "checked_by" to "사용자", "outcome" to "501호 현장 확인"), cookie)
        request("PATCH", "/api/cases/$id/properties/$property", mapOf("identity" to mapOf("building_dong" to "101", "unit_number" to "502", "area_basis" to "exclusive")), cookie)
        assertEquals("stale", jdbc.queryForObject("SELECT status FROM candidate_analyses WHERE property_id=?", String::class.java, property))
        assertNull(jdbc.queryForList("SELECT selected_property_id FROM purchase_cases WHERE id=?", id).single()["selected_property_id"])
        val review = json.readTree(jdbc.queryForObject("SELECT previous_snapshot::text FROM candidate_source_reviews WHERE property_id=?", String::class.java, property))
        assertEquals("501", review.path("identity").path("unit_number").asText())
        assertEquals("scheduled", jdbc.queryForObject("SELECT status FROM case_execution_tasks WHERE id=?", String::class.java, task))
        assertNull(jdbc.queryForList("SELECT completed_at FROM case_execution_tasks WHERE id=?", task).single()["completed_at"])
        val previous = json.readTree(jdbc.queryForObject("SELECT previous_execution::text FROM candidate_source_reviews WHERE property_id=?", String::class.java, property))
        assertEquals("501호 현장 확인", previous.first { it.path("id").asLong() == task }.path("outcome").asText())
    }
}
