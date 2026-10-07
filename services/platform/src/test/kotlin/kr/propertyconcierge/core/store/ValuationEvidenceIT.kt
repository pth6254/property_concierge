package kr.propertyconcierge.core.store

import com.fasterxml.jackson.databind.JsonNode
import kr.propertyconcierge.core.integration.PlatformIntegrationSupport
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.mockito.Mockito.doAnswer
import org.mockito.ArgumentMatchers.any
import org.mockito.ArgumentMatchers.eq
import org.springframework.beans.factory.annotation.Autowired
import kr.propertyconcierge.core.ApiFailure

class ValuationEvidenceIT : PlatformIntegrationSupport() {
    @Autowired lateinit var history: AnalysisHistoryStore
    @Autowired lateinit var cases: CaseStore
    @Test fun `조건부 참고자료를 저장 복원해도 가격 체크리스트를 완료하지 않는다`() {
        val (owner, cookie) = register(); val id = case(cookie)
        doAnswer { invocation ->
            val input = json.valueToTree<JsonNode>(invocation.getArgument<Any>(1))
            input.path("result").path("analysis_result")
        }.`when`(python).analyze(eq("appraisal/summary") ?: "", any(Any::class.java) ?: Any())
        for (kind in listOf("conditional_scenario", "public_reference", "partial_reference", "withheld", "unsupported")) {
            val property = candidate(cookie, id)
            val result = mapOf("analysis_result" to mapOf("result_kind" to kind, "estimated_value" to null,
                "valuation" to mapOf("policy_version" to "PC-AVM-1.0-runtime-1", "comparison_eligible" to false,
                    "subject" to mapOf("address" to "서울특별시 강남구 역삼동 123", "area_sqm" to 84.9, "subtype" to "apartment"))))
            val historyId = history.history("save", json.valueToTree(mapOf("user_id" to owner, "query" to "참고자료", "result" to result))) as Long
            assertEquals(true, cases.dispatch("link_appraisal", json.valueToTree(mapOf("user_id" to owner, "case_id" to id, "property_id" to property, "history_id" to historyId, "result" to result))))
            assertEquals("todo", jdbc.queryForObject("SELECT status FROM candidate_checklist_items WHERE property_id=? AND category='price'", String::class.java, property))
            val saved = json.valueToTree<JsonNode>(history.history("load_one", json.valueToTree(mapOf("user_id" to owner, "record_id" to historyId))))
            assertEquals(kind, saved.path("analysis_result").path("result_kind").asText())
            val summary = json.readTree(jdbc.queryForObject("SELECT summary::text FROM candidate_analyses WHERE property_id=?", String::class.java, property))
            assertTrue(summary.path("estimated_value").isNull)
            assertEquals("PC-AVM-1.0-runtime-1", summary.path("valuation").path("policy_version").asText())
        }
    }

    @Test fun `주소 면적 유형 동호가 다른 분석은 연결과 완료 표시를 롤백한다`() {
        val (owner, cookie) = register(); val id = case(cookie)
        val property = candidate(cookie, id, mapOf("identity" to mapOf("building_dong" to "101동", "unit_number" to "501")))
        doAnswer { invocation -> json.valueToTree<JsonNode>(invocation.getArgument<Any>(1)).path("result").path("analysis_result")
        }.`when`(python).analyze(eq("appraisal/summary") ?: "", any(Any::class.java) ?: Any())
        val subject = mapOf<String, Any>("address" to "서울특별시 강남구 역삼동 123", "area_sqm" to 84.9,
            "subtype" to "apartment", "dong" to "101동", "ho" to "501")
        for (patch in listOf(mapOf("address" to "다른 주소"), mapOf("area_sqm" to 59), mapOf("subtype" to "commercial"), mapOf("ho" to "502"))) {
            val result = mapOf("analysis_result" to mapOf("valuation" to mapOf("comparison_eligible" to true, "subject" to (subject + patch))))
            val record = history.history("save", json.valueToTree(mapOf("user_id" to owner, "query" to "대상 대조", "result" to result))) as Long
            val failure = assertThrows(ApiFailure::class.java) {
                cases.dispatch("link_appraisal", json.valueToTree(mapOf("user_id" to owner, "case_id" to id, "property_id" to property, "history_id" to record, "result" to result)))
            }
            assertEquals(422, failure.status)
            assertEquals(0L, count("candidate_analyses"))
            assertEquals("todo", jdbc.queryForObject("SELECT status FROM candidate_checklist_items WHERE property_id=? AND category='price'", String::class.java, property))
        }
    }
}
