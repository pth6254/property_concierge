package kr.propertyconcierge.core.store

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import jakarta.servlet.http.HttpServletRequest
import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.auth.SessionService
import org.springframework.web.bind.annotation.*

@RestController
class HistoryActivityController(private val store: AnalysisHistoryStore, private val sessions: SessionService, private val json: ObjectMapper) {
    private fun args(request: HttpServletRequest, values: Map<String, Any?> = emptyMap()) =
        json.valueToTree<JsonNode>(values + ("user_id" to sessions.required(request).id))
    @GetMapping("/api/history")
    fun history(request: HttpServletRequest, @RequestParam(defaultValue="20") limit: Int,
        @RequestParam(defaultValue="0") offset: Int, @RequestParam(defaultValue="") keyword: String): Map<String, Any?> {
        val args = args(request, mapOf("limit" to limit, "offset" to offset, "keyword" to keyword))
        return mapOf("total" to store.history("count_all", args), "items" to store.history(if (keyword.isBlank()) "load_all" else "search_by_query", args))
    }
    @GetMapping("/api/history/{recordId:[0-9]+}")
    fun detail(request: HttpServletRequest, @PathVariable recordId: Long) = store.history("load_one", args(request, mapOf("record_id" to recordId)))
        ?: throw ApiFailure(404, "이력 없음")
    @DeleteMapping("/api/history/{recordId:[0-9]+}")
    fun delete(request: HttpServletRequest, @PathVariable recordId: Long): Map<String, Boolean> {
        store.history("delete_one", args(request, mapOf("record_id" to recordId))); return mapOf("ok" to true)
    }
    @DeleteMapping("/api/history")
    fun clear(request: HttpServletRequest): Map<String, Boolean> { store.history("delete_all", args(request)); return mapOf("ok" to true) }
    @GetMapping("/api/activity")
    fun activity(request: HttpServletRequest, @RequestParam(defaultValue="8") limit: Int): Map<String, Any> {
        val args = args(request, mapOf("limit" to limit))
        val histories = json.valueToTree<JsonNode>(store.history("load_all", args)).map { row ->
            json.createObjectNode().apply {
                put("type", "appraisal"); set<JsonNode>("id", row.path("id")); set<JsonNode>("title", row.path("query"))
                put("subtitle", row.path("category").asText("")); set<JsonNode>("created", row.path("created"))
                for (field in listOf("estimated_value", "valuation_verdict", "investment_grade")) set<JsonNode>(field, row.get(field) ?: json.nullNode())
            }
        }
        val activities = json.valueToTree<JsonNode>(store.activity("load_recent", args)).map { row ->
            json.createObjectNode().apply {
                for (field in listOf("type", "id", "title", "created")) set<JsonNode>(field, row.path(field))
                set<JsonNode>("subtitle", row.path("summary"))
                if (row.path("meta").isObject) setAll<com.fasterxml.jackson.databind.node.ObjectNode>(row.path("meta") as com.fasterxml.jackson.databind.node.ObjectNode)
            }
        }
        return mapOf("items" to (histories + activities).sortedByDescending { it.path("created").asText("") }.take(limit))
    }
}
