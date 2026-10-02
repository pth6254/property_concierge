package kr.propertyconcierge.core.store

import kr.propertyconcierge.core.integration.PlatformIntegrationSupport
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class ExecutionPersistenceIT : PlatformIntegrationSupport() {
    private fun selected(): Pair<jakarta.servlet.http.Cookie, Long> {
        val (_, cookie) = register(); val id = case(cookie); val candidate = candidate(cookie, id)
        request("POST", "/api/cases/$id/decision", mapOf("property_id" to candidate, "reason" to "등록 조건을 검토하고 선택함"), cookie)
        return cookie to id
    }
    @Test fun `선택은 18개 기본 거래 준비 작업을 생성하고 조회로 중복되지 않는다`() {
        val (cookie, id) = selected()
        repeat(2) { assertEquals(18, body(request("GET", "/api/cases/$id/execution", cookie=cookie)).path("tasks").size()) }
        assertEquals(18L, count("case_execution_tasks")); assertEquals(1L, count("case_execution_plans"))
    }
    @Test fun `완료에는 확인자와 결과가 필요하고 기본 작업을 삭제하지 않는다`() {
        val (cookie, id) = selected()
        val task = body(request("GET", "/api/cases/$id/execution", cookie=cookie)).path("tasks").first().path("id").asLong()
        val path = "/api/cases/$id/execution/tasks/$task"
        request("PATCH", path, mapOf("status" to "done"), cookie, 422)
        request("PATCH", path, mapOf("status" to "done", "checked_by" to "사용자", "outcome" to "현장 확인 완료"), cookie)
        assertNotNull(jdbc.queryForObject("SELECT completed_at FROM case_execution_tasks WHERE id=?", String::class.java, task))
        request("DELETE", path, cookie=cookie, expected=422)
    }
    @Test fun `잘못된 잔금 일정은 저장되지 않고 사용자 작업만 삭제할 수 있다`() {
        val (cookie, id) = selected()
        request("PATCH", "/api/cases/$id/execution", mapOf("contract_planned_date" to "2027-02-01", "closing_planned_date" to "2027-01-01"), cookie, 422)
        assertNull(jdbc.queryForList("SELECT contract_planned_date FROM case_execution_plans WHERE case_id=?", id).single()["contract_planned_date"])
        val task = body(request("POST", "/api/cases/$id/execution/tasks", mapOf("phase" to "before_contract", "title" to "별도 소음 확인"), cookie, 201)).path("id").asLong()
        request("DELETE", "/api/cases/$id/execution/tasks/$task", cookie=cookie, expected=204)
        assertEquals(18L, count("case_execution_tasks"))
    }
}
