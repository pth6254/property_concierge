package kr.propertyconcierge.core.bridge

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import jakarta.servlet.http.HttpServletRequest
import jakarta.servlet.http.HttpServletResponse
import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.auth.SessionService
import kr.propertyconcierge.core.store.CaseStore
import org.springframework.web.bind.annotation.*

@RestController
class DataController(private val python: PythonClient, private val sessions: SessionService, private val store: CaseStore, private val json: ObjectMapper) {
    private fun case(request: HttpServletRequest, id: Long): Any = store.dispatch("get_case", json.valueToTree(mapOf("case_id" to id, "user_id" to sessions.required(request).id)))
        ?: throw ApiFailure(404, "검토 케이스가 없습니다")
    @GetMapping("/api/market/regions", "/api/market/regions/summary", "/api/market/districts")
    fun market(request: HttpServletRequest, response: HttpServletResponse) {
        sessions.required(request)
        val path = request.requestURI.removePrefix("/api") + (request.queryString?.let { "?$it" } ?: "")
        val reply = python.send("GET", "/internal/v1/data$path")
        response.status=reply.status; response.contentType="application/json"; response.outputStream.write(reply.body)
    }
    @GetMapping("/api/simulation/market-rate")
    fun rate() = python.analyze("data/mortgage-rate", emptyMap<String, Any>())
    @PostMapping("/api/cases/{caseId:[0-9]+}/funding-scenarios")
    fun funding(request: HttpServletRequest, @PathVariable caseId: Long, @RequestBody body: JsonNode): Any {
        val snapshot = case(request, caseId)
        return python.analyze("analysis/funding-scenarios", mapOf("case" to snapshot, "request" to body))
    }
    @GetMapping("/api/cases/{caseId:[0-9]+}/recommendations")
    fun recommend(request: HttpServletRequest, @PathVariable caseId: Long, @RequestParam("region_code") regionCode: String,
        @RequestParam("require_complete_address", defaultValue="false") complete: Boolean): Any {
        if (!regionCode.matches(Regex("[0-9]{10}"))) throw ApiFailure(422, "지역 코드를 확인해주세요")
        return python.analyze("analysis/case-recommendations", mapOf("case" to case(request, caseId), "region_code" to regionCode, "require_complete_address" to complete))
    }
    @PostMapping("/api/cases/{caseId:[0-9]+}/regions")
    @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
    fun addRegion(request: HttpServletRequest, @PathVariable caseId: Long, @RequestBody body: JsonNode): Any {
        val snapshot = case(request, caseId)
        val data = python.analyze("data/case-region", mapOf("case" to snapshot, "request" to body))
        return store.dispatch("add_region", json.valueToTree(mapOf("case_id" to caseId, "user_id" to sessions.required(request).id, "data" to data)))
            ?: throw ApiFailure(404, "검토 케이스가 없습니다")
    }
    @DeleteMapping("/api/cases/{caseId:[0-9]+}/regions/{regionId:[0-9]+}")
    @ResponseStatus(org.springframework.http.HttpStatus.NO_CONTENT)
    fun deleteRegion(request: HttpServletRequest, @PathVariable caseId: Long, @PathVariable regionId: Long) {
        if (store.dispatch("delete_region", json.valueToTree(mapOf("case_id" to caseId, "region_id" to regionId, "user_id" to sessions.required(request).id))) != true)
            throw ApiFailure(404, "관심 지역이 없습니다")
    }
}
