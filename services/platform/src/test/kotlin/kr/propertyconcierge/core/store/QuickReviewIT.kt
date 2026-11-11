package kr.propertyconcierge.core.store

import kr.propertyconcierge.core.integration.PlatformIntegrationSupport
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.mockito.ArgumentMatchers.any
import org.mockito.ArgumentMatchers.anyString
import org.mockito.ArgumentMatchers.eq
import org.mockito.Mockito.doReturn
import org.mockito.Mockito.never
import org.mockito.Mockito.verify

class QuickReviewIT : PlatformIntegrationSupport() {
    @Test fun `한 번에 검토는 본인 후보만 확인한 뒤 행위자와 함께 분석 서비스에 넘긴다`() {
        val (ownerId, owner) = register()
        val caseId = case(owner)
        val propertyId = candidate(owner, caseId)
        val reply = json.readTree("""{"case_id":$caseId,"candidate_id":$propertyId,"funding":{"status":"needs_input","missing":["cash_available"]},
            "appraisal":{"status":"queued","job_id":"0123456789abcdef"},"rights":{"status":"needs_document"}}""")
        doReturn(reply).`when`(python).analyzeAs(eq("ai/candidate-review") ?: "", any(Any::class.java) ?: Any(), eq(ownerId))

        request("POST", "/api/cases/$caseId/properties/$propertyId/quick-review", expected = 401)
        val (_, other) = register()
        request("POST", "/api/cases/$caseId/properties/$propertyId/quick-review", cookie = other, expected = 404)
        request("POST", "/api/cases/$caseId/properties/999999/quick-review", cookie = owner, expected = 404)
        // 타인·없는 후보는 분석 서비스까지 가지 않는다.
        verify(python, never()).analyzeAs(anyString(), any(Any::class.java) ?: Any(), any())

        val result = body(request("POST", "/api/cases/$caseId/properties/$propertyId/quick-review", cookie = owner))
        assertEquals("queued", result.path("appraisal").path("status").asText())
        assertEquals("needs_document", result.path("rights").path("status").asText())
        verify(python).analyzeAs(eq("ai/candidate-review") ?: "", eq(mapOf("case_id" to caseId, "candidate_id" to propertyId)) ?: Any(), eq(ownerId))
    }
}
