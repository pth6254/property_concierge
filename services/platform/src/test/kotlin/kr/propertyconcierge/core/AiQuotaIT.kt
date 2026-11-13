package kr.propertyconcierge.core

import kr.propertyconcierge.core.integration.PlatformIntegrationSupport
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.mockito.ArgumentMatchers.any
import org.mockito.ArgumentMatchers.eq
import org.mockito.Mockito.doReturn

class AiQuotaIT : PlatformIntegrationSupport() {
    @Test fun `AI 요청은 로그인이 필요하고 비로그인 요청은 분석 서비스까지 가지 않는다`() {
        request("POST", "/api/appraisal/jobs", mapOf("user_input" to "서울 아파트"), expected = 401)
        request("POST", "/api/chat/jobs", mapOf("question" to "취득세"), expected = 401)
        request("POST", "/api/chat", mapOf("question" to "취득세"), expected = 401)
        request("POST", "/api/recommendation", mapOf("query" to "강남"), expected = 401)
        assertTrue(org.mockito.Mockito.mockingDetails(python).invocations.isEmpty(), "비로그인 요청이 분석 서비스를 호출함")
    }

    @Test fun `사용자별 하루 한도를 넘으면 429이고 다른 사용자에게는 영향이 없다`() {
        val (ownerId, owner) = register()
        val caseId = case(owner)
        val propertyId = candidate(owner, caseId)
        doReturn(json.readTree("""{"case_id":$caseId,"candidate_id":$propertyId,"funding":{"status":"current"},
            "appraisal":{"status":"current"},"rights":{"status":"needs_document"}}"""))
            .`when`(python).analyzeAs(eq("ai/candidate-review") ?: "", any(Any::class.java) ?: Any(), eq(ownerId))
        // 한 번에 검토는 시세추정 작업을 접수하므로 시세추정 한도(기본 30회)를 쓴다.
        repeat(30) { request("POST", "/api/cases/$caseId/properties/$propertyId/quick-review", cookie = owner) }
        val blocked = request("POST", "/api/cases/$caseId/properties/$propertyId/quick-review", cookie = owner, expected = 429)
        assertTrue(blocked.response.contentAsString.contains("시세추정 이용 한도(30회)"))
        // 한도는 한국 날짜 기준 키에 쌓인다.
        assertNotNull(redis.opsForValue().get("ai-quota:appraisal:$ownerId:${java.time.LocalDate.now(java.time.ZoneId.of("Asia/Seoul"))}"))

        val (_, other) = register()
        val otherCase = case(other)
        val otherProperty = candidate(other, otherCase)
        request("POST", "/api/cases/$otherCase/properties/$otherProperty/quick-review", cookie = other, expected = 200)
    }
}
