package kr.propertyconcierge.core.calculations

import kr.propertyconcierge.core.integration.PlatformIntegrationSupport
import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.store.CaseStore
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired

class FundingPersistenceIT : PlatformIntegrationSupport() {
    @Autowired lateinit var store: CaseStore
    private fun funding(caseId: Long, property: Long, price: Long = 800_000_000) = mapOf("purchase_price" to price,
        "case_id" to caseId, "candidate_id" to property, "cash_available" to 500_000_000, "loan_ratio" to 0.5,
        "annual_interest_rate" to 4, "loan_years" to 30, "owned_homes" to 1, "annual_income" to 100_000_000,
        "monthly_payment_limit" to 3_000_000)
    @Test fun `후보 자금은 실제 Kotlin 계산 결과와 기준 조건을 저장한다`() {
        val (_, cookie) = register(); val id = case(cookie); val property = candidate(cookie, id)
        val result = body(request("POST", "/api/simulation", funding(id, property), cookie))
        val saved = json.readTree(jdbc.queryForObject("SELECT summary::text FROM candidate_analyses WHERE property_id=?", String::class.java, property))
        assertEquals(result.path("result").path("required_cash"), saved.path("required_cash"))
        assertEquals(400_000_000L, saved.path("loan_amount").asLong())
        assertEquals("after_purchase", saved.path("home_count_basis").asText())
        assertEquals(1, saved.path("inputs").path("owned_homes").asInt())
        assertEquals("kotlin-spring", saved.path("calculator_engine").asText())
        assertTrue(saved.path("calculation_version").asText().isNotBlank()); assertEquals("2026-01-01", saved.path("tax_rules_as_of").asText())
    }
    @Test fun `타인 후보와 다른 가격으로 계산한 결과는 저장하지 않는다`() {
        val (_, cookie) = register(); val id = case(cookie); val property = candidate(cookie, id)
        val (_, other) = register()
        request("POST", "/api/simulation", funding(id, property), other, 404)
        request("POST", "/api/simulation", funding(id, property, 900_000_000), cookie, 422)
        assertEquals(0L, count("candidate_analyses"))
    }
    @Test fun `보고서 생성 도중 후보가 변경되면 늦게 끝난 계산을 연결하지 않는다`() {
        val (_, cookie) = register(); val id = case(cookie); val property = candidate(cookie, id)
        duringReport = { jdbc.update("UPDATE case_properties SET asking_price=900000000 WHERE id=?", property) }
        request("POST", "/api/simulation", funding(id, property), cookie, 422)
        assertEquals(0L, count("candidate_analyses"))
        assertEquals(900_000_000L, jdbc.queryForObject("SELECT asking_price FROM case_properties WHERE id=?", Long::class.java, property))
    }
    @Test fun `내부 분석 연결도 다른 가격이나 금액 누락을 거부한다`() {
        val (owner, cookie) = register(); val id = case(cookie); val property = candidate(cookie, id)
        for (summary in listOf(mapOf("purchase_price" to 900_000_000), emptyMap<String, Any>())) {
            val args = json.valueToTree<com.fasterxml.jackson.databind.JsonNode>(mapOf("user_id" to owner, "case_id" to id,
                "property_id" to property, "analysis_type" to "simulation", "summary" to summary))
            assertEquals(422, assertThrows(ApiFailure::class.java) { store.dispatch("link_candidate_analysis", args) }.status)
        }
        assertEquals(0L, count("candidate_analyses"))
        assertEquals("todo", jdbc.queryForObject("SELECT status FROM candidate_checklist_items WHERE property_id=? AND category='funding'", String::class.java, property))
    }
}
