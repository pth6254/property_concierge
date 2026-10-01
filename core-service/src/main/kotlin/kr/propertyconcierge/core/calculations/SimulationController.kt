package kr.propertyconcierge.core.calculations

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import jakarta.servlet.http.HttpServletRequest
import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.auth.SessionService
import kr.propertyconcierge.core.bridge.PythonClient
import kr.propertyconcierge.core.store.CaseStore
import org.springframework.web.bind.annotation.*
import org.springframework.core.env.Environment
import java.security.MessageDigest

data class InternalFundingRequest(val request: FundingRequest, val userId: Long? = null)

@RestController
class SimulationController(private val calculator: FinanceCalculator, private val sessions: SessionService,
    private val store: CaseStore, private val python: PythonClient, private val json: ObjectMapper, env: Environment) {
    private val key = env.getRequiredProperty("INTERNAL_SERVICE_SECRET").also { require(it.length >= 32) }
    @PostMapping("/api/simulation")
    fun simulate(request: HttpServletRequest, @RequestBody body: FundingRequest) = execute(body, sessions.optional(request)?.id)

    @PostMapping("/internal/v1/simulation")
    fun internal(@RequestBody body: InternalFundingRequest,
        @RequestHeader("X-Internal-Service-Key", required = false) provided: String?): Map<String, Any> {
        if (provided == null || !MessageDigest.isEqual(key.toByteArray(), provided.toByteArray())) throw ApiFailure(401, "내부 서비스 인증이 필요합니다")
        if (body.userId != null && (body.userId <= 0 || sessions.userById(body.userId) == null)) throw ApiFailure(404, "사용자를 찾을 수 없습니다")
        return execute(body.request, body.userId)
    }

    fun execute(body: FundingRequest, userId: Long?): Map<String, Any> {
        val linked = body.caseId != null || body.candidateId != null
        if (linked && (userId == null || body.caseId == null || body.candidateId == null))
            throw ApiFailure(422, "케이스와 후보를 함께 지정하고 로그인해주세요")
        val owner = if (linked) json.valueToTree<JsonNode>(mapOf("user_id" to requireNotNull(userId),
            "case_id" to body.caseId, "property_id" to body.candidateId)) else null
        if (owner != null && store.dispatch("validate_candidate", owner) != true) throw ApiFailure(404, "검토 후보를 찾을 수 없습니다")
        val expectedInputs = owner?.let { store.dispatch("candidate_inputs", it) }
        val input = body.input()
        val result = try { calculator.calculate(input) } catch (_: ArithmeticException) {
            throw ApiFailure(422, "예상 금액이 계산 범위를 초과합니다. 금액·기간·상승률을 조정해주세요")
        }
        // 기존 리포트 형식을 유지하기 위한 표현 단계다. Python은 전달된 결과를 다시 계산하지 않는다.
        val report = python.analyze("simulation/report", mapOf("input" to input, "result" to result))
        val response = mutableMapOf<String, Any>("simulation_input" to input, "built_input" to input, "result" to result,
            "report" to report.path("report"), "report_output" to report.path("report_output"), "error" to "")
        if (owner != null) {
            val summary = body.summary(result, json)
            val args = json.valueToTree<JsonNode>(mapOf("user_id" to requireNotNull(userId), "case_id" to body.caseId,
                "property_id" to body.candidateId, "analysis_type" to "simulation", "summary" to summary,
                "checklist_status" to if (body.needsReview(result)) "warning" else "done",
                "evidence" to "사용자가 입력한 금융 조건으로 자금 시뮬레이션 완료", "expected_inputs" to expectedInputs))
            if (store.dispatch("link_candidate_analysis", args) != true) throw ApiFailure(404, "검토 후보를 찾을 수 없습니다")
            response["candidate_funding"] = summary
        }
        return response
    }
}
