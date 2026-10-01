package kr.propertyconcierge.core.bridge

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import jakarta.servlet.http.HttpServletRequest
import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.auth.RedisLimits
import kr.propertyconcierge.core.auth.SessionService
import kr.propertyconcierge.core.auth.ChatQuota
import kr.propertyconcierge.core.listings.ListingObservationStore
import kr.propertyconcierge.core.store.AiJobStore
import kr.propertyconcierge.core.store.CaseStore
import org.springframework.data.redis.core.StringRedisTemplate
import org.springframework.web.bind.annotation.*
import java.time.Duration

@RestController
class AiWorkController(private val jobs: AiJobStore, private val sessions: SessionService, private val python: PythonClient,
    private val cases: CaseStore, private val json: ObjectMapper, private val limits: RedisLimits,
    private val redis: StringRedisTemplate, private val observations: ListingObservationStore, private val quota:ChatQuota) {
    @PostMapping("/api/appraisal/jobs", "/api/chat/jobs", "/api/concierge/jobs")
    fun create(request: HttpServletRequest, @RequestBody body: JsonNode): Map<String, Any?> {
        val task = request.requestURI.removePrefix("/api/").substringBefore('/')
        val owner = if (task == "concierge") sessions.required(request).id else sessions.optional(request)?.id
        limits.check("$task-jobs", request.remoteAddr, if (task == "chat") 10 else 5, 60)
        val valid = python.analyze("ai/validate", mapOf("task_type" to task, "request" to body))
        if (task == "chat") quota.check(owner)
        var expected: Any? = null
        if (task == "appraisal" && (valid.hasNonNull("case_id") || valid.hasNonNull("candidate_id"))) {
            if (owner == null || !valid.hasNonNull("case_id") || !valid.hasNonNull("candidate_id")) throw ApiFailure(404, "검토 후보가 없습니다")
            val args = json.valueToTree<JsonNode>(mapOf("case_id" to valid.path("case_id").asLong(), "property_id" to valid.path("candidate_id").asLong(), "user_id" to owner))
            if (cases.dispatch("validate_candidate", args) != true) throw ApiFailure(404, "검토 후보가 없습니다")
            if (!valid.path("save_history").asBoolean(true)) throw ApiFailure(422, "후보 연결 분석은 이력 저장이 필요합니다")
            expected = cases.dispatch("candidate_inputs", args)
        }
        return enqueue(task, mapOf("request" to valid, "expected_candidate_inputs" to expected), owner)
    }
    private fun enqueue(task: String, payload: Any, owner: Long?): Map<String, Any?> = mapOf("job_id" to jobs.dispatch("create_task",
        json.valueToTree(mapOf("task_type" to task, "payload" to payload, "owner_id" to owner))))
    @PostMapping("/api/listings/collection/jobs")
    @ResponseStatus(org.springframework.http.HttpStatus.ACCEPTED)
    fun collect(request: HttpServletRequest, @RequestBody body: CollectionInput): Map<String, Any?> {
        val owner = sessions.required(request).id
        val url = observations.canonical(body.sourceUrl)
        val wait = redis.getExpire("listing-collection:naver:next-request")
        if (wait > 0) throw ApiFailure(429, "네이버 원문 수집을 잠시 쉬고 있습니다. 약 ${wait}초 후 직접 다시 시도해주세요. 자동 재시도하지 않습니다. 원문을 확인할 수 있다면 링크로 수동 등록할 수 있습니다.", wait)
        val key = "listing-collection-cooldown:$owner"
        if (redis.opsForValue().setIfAbsent(key, "1", Duration.ofSeconds(60)) != true) throw ApiFailure(429, "수집 요청 후 1분이 지나면 다시 시도해주세요", 60)
        return try { enqueue("listing_collection", mapOf("url" to url), owner) } catch (error: Exception) { redis.delete(key); throw error }
    }
    @GetMapping("/api/listings/collection/history")
    fun history(request: HttpServletRequest, @RequestParam("source_url") source: String): Any? {
        val owner = sessions.required(request).id
        observations.canonical(source)
        return observations.dispatch("history", json.valueToTree(mapOf("user_id" to owner, "url" to source)))
    }
}
data class CollectionInput(val sourceUrl: String)
