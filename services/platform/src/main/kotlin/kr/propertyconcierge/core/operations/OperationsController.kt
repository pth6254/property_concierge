package kr.propertyconcierge.core.operations

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import jakarta.servlet.http.HttpServletRequest
import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.auth.SessionService
import kr.propertyconcierge.core.bridge.PythonClient
import kr.propertyconcierge.core.store.AiJobStore
import org.springframework.core.env.Environment
import org.springframework.data.redis.connection.Limit
import org.springframework.data.redis.core.StringRedisTemplate
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.web.bind.annotation.*
import java.nio.file.Files
import java.nio.file.Path
import java.time.Duration
import java.time.LocalDate
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

@RestController
@RequestMapping("/api/operations")
class OperationsController(private val sessions: SessionService, private val jdbc: JdbcTemplate,
    private val redis: StringRedisTemplate, private val json: ObjectMapper, private val jobs: AiJobStore,
    private val python: PythonClient, env: Environment) {
    private val backupPath = Path.of(env.getProperty("BACKUP_STATUS_PATH", "/app/backups/backup-status.json"))
    private fun operator(request: HttpServletRequest): Long {
        val user = sessions.required(request)
        if (!sessions.operator(user)) throw ApiFailure(403, "운영자 권한이 필요합니다")
        return user.id
    }
    @GetMapping("/status")
    fun status(request: HttpServletRequest): JsonNode {
        operator(request)
        // AI 실행기의 생존·큐 상태는 그 런타임이 보고한다. 공개 권한 판단은 Spring에서 끝낸다.
        val state = python.analyze("data/runtime-status", emptyMap<String,Any>()) as com.fasterxml.jackson.databind.node.ObjectNode
        val alerts = runCatching { redis.opsForStream<String,String>().reverseRange("property-jobs:ops-alerts", org.springframework.data.domain.Range.unbounded(), Limit.limit().count(20))
            ?.map { record -> mapOf("id" to record.id.value, "status" to record.value["status"], "at" to record.value["at"], "checks" to json.readTree(record.value["checks"])) } ?: emptyList() }.getOrDefault(emptyList())
        state.set<JsonNode>("alerts", json.valueToTree(alerts))
        return state
    }
    @GetMapping("/backup")
    fun backup(request: HttpServletRequest): Map<String,Any?> {
        operator(request)
        return runCatching {
            val value = json.readTree(Files.readString(backupPath))
            require(value.path("checked_at").isNumber && value.path("bytes").isIntegralNumber)
            val checked = value.path("checked_at").asDouble()
            val status = value.path("status").asText()
            mapOf("status" to if (status == "ok" && System.currentTimeMillis()/1000.0-checked > 26*3600) "stale" else status,
                "checked_at" to checked, "bytes" to value.path("bytes").asLong(),
                "notice" to "백업 파일 생성·목록 읽기 검사입니다. 실제 복원 성공은 격리 DB 복원으로 별도 확인해야 합니다.")
        }.getOrElse { mapOf("status" to "unknown", "checked_at" to null, "bytes" to null,
            "notice" to "정기 백업 기록이 없습니다. maintenance 프로필의 database-backup을 활성화하세요.") }
    }
    @GetMapping("/complexes")
    fun complexes(request: HttpServletRequest, @RequestParam("lawd_code",defaultValue="11350") code: String,
        @RequestParam(defaultValue="1") page: Int): Map<String,Any?> {
        operator(request)
        if (!code.matches(Regex("[0-9]{5}")) || page !in 1..1000000) throw ApiFailure(422,"지역·페이지를 확인해주세요")
        val rows = jdbc.queryForList("SELECT id,name,dong,aliases,status,address,checked_at FROM complex_catalog WHERE lawd_code=? ORDER BY id LIMIT 30 OFFSET ?",code,(page-1)*30)
            .map { row -> row.toMutableMap().apply { for (field in listOf("aliases","address")) this[field]=json.readTree(row[field].toString()) } }
        return mapOf("total" to jdbc.queryForObject("SELECT count(*) FROM complex_catalog WHERE lawd_code=?",Long::class.java,code),"page" to page,"items" to rows)
    }
    @PostMapping("/complexes/{catalogId:[0-9]+}/refresh")
    fun refresh(request: HttpServletRequest,@PathVariable catalogId: Long): Any {
        val owner=operator(request)
        if (jdbc.queryForObject("SELECT count(*) FROM complex_catalog WHERE id=?",Int::class.java,catalogId) == 0) throw ApiFailure(404,"단지 기준정보가 없습니다")
        return enqueue("complex_refresh",json.valueToTree(mapOf("catalog_id" to catalogId)),owner)
    }
    @GetMapping("/ingestion")
    fun ingestion(request: HttpServletRequest,@RequestParam("lawd_code",defaultValue="11350") code:String,
        @RequestParam(defaultValue="12") months:Int): JsonNode {
        operator(request)
        if (!code.matches(Regex("[0-9]{5}")) || months !in 1..24) throw ApiFailure(422,"수집 범위를 확인해주세요")
        val reply=python.send("GET","/internal/v1/data/ingestion?lawd_code=$code&months=$months")
        if(reply.status!=200) throw ApiFailure(reply.status,"수집 현황을 조회하지 못했습니다")
        return json.readTree(reply.body)
    }
    @PostMapping("/ingestion/retry")
    fun retry(request:HttpServletRequest,@RequestBody body:JsonNode):Any {
        val owner=operator(request)
        return enqueue("ingestion_retry",python.analyze("data/ingestion/validate-retry",body),owner)
    }
    private fun enqueue(task:String,payload:JsonNode,owner:Long):Any {
        val normalized = java.util.TreeMap<String,JsonNode>().apply { payload.fields().forEachRemaining { put(it.key,it.value) } }
        val key="ops-request:$task:${json.writeValueAsString(normalized)}"
        if(redis.opsForValue().setIfAbsent(key,"reserved",Duration.ofMinutes(10))!=true) throw ApiFailure(409,"이미 요청된 작업입니다. 10분 후 다시 확인하세요.")
        return try { mapOf("job_id" to jobs.dispatch("create_task",json.valueToTree(mapOf("task_type" to task,"payload" to payload,"owner_id" to owner)))) }
        catch(error:Exception) { redis.delete(key); throw error }
    }
    @GetMapping("/jobs/{jobId}")
    fun job(request:HttpServletRequest,@PathVariable jobId:String):Any = jobs.get(jobId,operator(request)) ?: throw ApiFailure(404,"작업이 없습니다")
    @GetMapping("/listing-quality")
    fun listingQuality(request:HttpServletRequest):Any {
        operator(request)
        val counts=jdbc.queryForList("SELECT outcome,count(*) AS count FROM listing_observations GROUP BY outcome").associate { it["outcome"].toString() to it["count"] }
        return mapOf("counts" to counts,"notice" to "원문 추출 상태 집계이며 사람의 정답 대조 결과나 매물 존재율이 아닙니다.")
    }
    @GetMapping("/metrics")
    fun metrics(request:HttpServletRequest,@RequestParam(defaultValue="7") days:Int):Any {
        operator(request)
        if(days !in 1..30) throw ApiFailure(422,"조회 기간을 확인해주세요")
        val dates=(0 until days).map { LocalDate.now(ZoneOffset.UTC).minusDays(it.toLong()).format(DateTimeFormatter.BASIC_ISO_DATE) }
        val features=dates.flatMap { redis.opsForSet().members("metrics:features:$it") ?: emptySet() }.toSortedSet()
        val rows=features.map { feature ->
            val totals=mutableMapOf<String,Double>()
            for(day in dates) for((key,value) in redis.opsForHash<String,String>().entries("metrics:duration:$day:$feature")) totals[key]=(totals[key] ?: 0.0)+(value.toDoubleOrNull() ?: 0.0)
            val count=totals["requests"] ?: 0.0; val failures=totals["failures"] ?: 0.0
            var accumulated=0.0
            val p95=listOf("0.1","0.5","1","3","10","30","60","120","300","900").firstOrNull { accumulated += totals["bucket:$it"] ?: 0.0; count>0 && accumulated>=count*0.95 }?.toDouble()
            mapOf("feature" to feature,"requests" to count.toLong(),"failures" to failures.toLong(),"failure_rate" to if(count>0) failures/count else null,
                "mean_seconds" to if(count>0) (totals["total_seconds"] ?: 0.0)/count else null,"p95_upper_seconds" to p95)
        }
        val steps=listOf("case_created","conditions_saved","candidate_added","comparison_viewed","candidate_selected").associateWith { step -> dates.flatMap { redis.opsForSet().members("metrics:step:$it:$step") ?: emptySet() }.toSet().size }
        return mapOf("days" to days,"features" to rows,"steps" to steps,"notice" to "UTC 기준 최근 기간. 단계별 고유 사용자 수이며 동일 코호트의 전환율이 아닙니다. p95는 히스토그램 상한이며 900초 초과는 미표시. HTTP 실패는 5xx, 작업 실패는 작업 결과 기준입니다.")
    }
}
