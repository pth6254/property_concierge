package kr.propertyconcierge.core.calculations

import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.CoreConfiguration
import kr.propertyconcierge.core.auth.SessionService
import kr.propertyconcierge.core.bridge.PythonClient
import kr.propertyconcierge.core.store.CaseStore
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.mockito.Mockito.mock
import org.springframework.mock.env.MockEnvironment

class SimulationControllerTest {
    private val json = CoreConfiguration().objectMapper()
    private val key = "isolated-simulation-key-" + "a".repeat(32)

    private fun controller(saved: Boolean, beforeSave: () -> Unit = {}): SimulationController {
        val store = mock(CaseStore::class.java) { call ->
            when (call.arguments.firstOrNull()) {
                "validate_candidate" -> true
                "candidate_inputs" -> mapOf("asking_price" to 600_000_000L)
                "link_candidate_analysis" -> { beforeSave(); saved }
                else -> null
            }
        }
        val python = mock(PythonClient::class.java) { call ->
            if (call.method.name == "analyze") json.readTree("""{"report":{},"report_output":{}}""") else null
        }
        return SimulationController(FinanceCalculator(), mock(SessionService::class.java), store, python, json,
            MockEnvironment().withProperty("INTERNAL_SERVICE_SECRET", key))
    }

    @Test fun `계산 중 후보가 삭제되면 저장 성공 결과를 반환하지 않는다`() {
        val failure = assertThrows(ApiFailure::class.java) {
            controller(false).execute(FundingRequest(600_000_000, caseId=1, candidateId=2), 3)
        }
        assertEquals(404, failure.status)
    }
    @Test fun `저장 단계의 가격 변경 거부를 유지한다`() {
        val failure = assertThrows(ApiFailure::class.java) {
            controller(false) { throw ApiFailure(422, "가격이 변경되었습니다") }
                .execute(FundingRequest(600_000_000, caseId=1, candidateId=2), 3)
        }
        assertEquals(422, failure.status)
    }
    @Test fun `내부 자금 실행도 서비스 인증과 소유자를 요구한다`() {
        val controller = controller(true)
        assertEquals(401, assertThrows(ApiFailure::class.java) {
            controller.internal(InternalFundingRequest(FundingRequest(600_000_000)), "wrong")
        }.status)
        assertEquals(404, assertThrows(ApiFailure::class.java) {
            controller.internal(InternalFundingRequest(FundingRequest(600_000_000), -1), key)
        }.status)
        assertEquals(422, assertThrows(ApiFailure::class.java) {
            controller.execute(FundingRequest(600_000_000, caseId=1, candidateId=2), null)
        }.status)
    }
}
