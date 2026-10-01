package kr.propertyconcierge.core.store

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import com.fasterxml.jackson.databind.node.ObjectNode
import kr.propertyconcierge.core.ApiFailure
import org.springframework.data.redis.core.StringRedisTemplate
import org.springframework.data.redis.core.script.DefaultRedisScript
import org.springframework.stereotype.Service
import java.time.Duration
import java.util.UUID

@Service
class AiJobStore(private val redis: StringRedisTemplate, private val json: ObjectMapper) {
    private fun id(value: String) = value.also { if (!it.matches(Regex("[0-9a-f]{16}"))) throw ApiFailure(422, "작업 ID 형식을 확인해주세요") }
    private val enqueue = DefaultRedisScript<String>("""
        redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
        return redis.call('XADD', KEYS[2], '*', 'job_id', ARGV[3], 'task_type', ARGV[4], 'payload', ARGV[5])
    """.trimIndent(), String::class.java)
    fun load(jobId: String): ObjectNode? = redis.opsForValue().get("job:${id(jobId)}")?.let { json.readTree(it) as ObjectNode }
    fun get(jobId: String, owner: Long?, includeResult: Boolean = true): ObjectNode? {
        val job = load(jobId) ?: return null
        if (job.hasNonNull("owner_id") && job.path("owner_id").asLong() != owner) return null
        return json.createObjectNode().apply {
            put("job_id", job.path("id").asText())
            for (key in listOf("status", "step", "error")) set<JsonNode>(key, job.get(key))
            val extra = job.path("extra") as? ObjectNode
            if (extra != null) setAll<ObjectNode>(extra)
            if (includeResult && job.path("status").asText() in setOf("done", "error")) set<JsonNode>("result", job.get("result"))
        }
    }
    fun dispatch(operation: String, args: JsonNode): Any? = when (operation) {
        "create_task" -> {
            val task = args.path("task_type").asText()
            if (task !in setOf("probe", "complex_refresh", "ingestion_retry", "appraisal", "candidate_appraisal", "listing_collection", "chat", "concierge"))
                throw ApiFailure(422, "지원하지 않는 AI 작업입니다")
            val jobId = UUID.randomUUID().toString().replace("-", "").take(16)
            val job = mapOf("id" to jobId, "status" to "queued", "step" to "", "created_at" to System.currentTimeMillis()/1000.0,
                "finished_at" to 0.0, "result" to null, "error" to "", "extra" to emptyMap<String, Any>(),
                "owner_id" to args.get("owner_id")?.takeUnless(JsonNode::isNull)?.asLong())
            redis.execute(enqueue, listOf("job:$jobId", "property-jobs"), json.writeValueAsString(job), "7200", jobId, task, args.path("payload").toString())
            // String 반환은 Spring의 텍스트 변환기를 타므로 JSON 노드로 계약을 고정한다.
            json.valueToTree<JsonNode>(jobId)
        }
        "_load" -> load(args.path("job_id").asText())
        "_save" -> {
            val jobId = id(args.path("job_id").asText()); val ttl = args.path("ttl").asLong()
            if (ttl !in 1..7200 || args.path("job").path("id").asText() != jobId || args.path("job").path("status").asText() !in setOf("queued", "running", "done", "error"))
                throw ApiFailure(422, "작업 상태와 보관 기간을 확인해주세요")
            redis.opsForValue().set("job:$jobId", args.path("job").toString(), Duration.ofSeconds(ttl)); null
        }
        "get" -> get(args.path("job_id").asText(), args.get("requester_id")?.takeUnless(JsonNode::isNull)?.asLong(), args.path("include_result").asBoolean(true))
        else -> throw ApiFailure(404, "AI 작업 저장 경로가 없습니다")
    }
}
