package kr.propertyconcierge.core.store

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import com.fasterxml.jackson.databind.node.ObjectNode
import kr.propertyconcierge.core.ApiFailure
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.stereotype.Service
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

@Service
class AnalysisHistoryStore(private val jdbc: JdbcTemplate, private val json: ObjectMapper) {
    private fun now() = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"))
    private fun owner(args: JsonNode) = args.get("user_id")?.takeUnless(JsonNode::isNull)?.asLong()
    private fun limit(args: JsonNode, default: Int) = args.path("limit").asInt(default).also {
        if (it !in 1..1000) throw ApiFailure(422, "조회 개수를 확인해주세요")
    }
    private fun row(raw: Map<String, Any?>): ObjectNode = json.valueToTree<ObjectNode>(raw).apply {
        for (key in listOf("result", "meta")) raw[key]?.let { set<JsonNode>(key, json.readTree(it.toString())) }
    }
    private fun historyView(raw: Map<String, Any?>): ObjectNode {
        val stored = row(raw)
        val result = stored.path("result") as ObjectNode
        val output = json.createObjectNode().apply { for (field in listOf("id", "query", "category", "created")) set<JsonNode>(field, stored.get(field)) }
        output.setAll<ObjectNode>(result)
        val analysis = result.path("analysis_result")
        for (key in listOf("estimated_value", "value_min", "value_max", "price_per_pyeong", "regional_avg_per_pyeong", "valuation_verdict", "deviation_pct",
            "cap_rate", "investment_grade", "annual_income", "appraisal_opinion", "strengths", "risk_factors", "recommendation", "comparable_avg", "comparable_count", "roi_5yr"))
            if (!output.has(key) && analysis.has(key)) output.set<JsonNode>(key, analysis.get(key))
        return output
    }
    fun history(operation: String, args: JsonNode): Any? {
        val user = owner(args)
        // 서비스 내부 집계에도 사용자 조건 없는 조회·삭제를 허용하지 않는다.
        if (operation != "save" && user == null) throw ApiFailure(422, "이력 소유자가 필요합니다")
        return when (operation) {
            "save" -> {
                val result = args.path("result")
                val category = result.path("analysis_result").path("agent_name").asText().ifBlank { result.path("category").asText("") }
                val job = args.get("job_id")?.takeUnless(JsonNode::isNull)?.asText()?.takeIf(String::isNotBlank)
                jdbc.queryForObject("""INSERT INTO history(user_id,job_id,query,category,result,created) VALUES (?,?,?,?,?::json,?)
                    ON CONFLICT(job_id) DO UPDATE SET job_id=excluded.job_id
                    WHERE history.user_id IS NOT DISTINCT FROM excluded.user_id RETURNING id""", Long::class.java,
                    user, job, args.path("query").asText(), category, result.toString(), now()) ?: throw ApiFailure(409, "분석 작업의 소유자가 일치하지 않습니다")
            }
            "count_all" -> jdbc.queryForObject("SELECT count(*) FROM history WHERE user_id=?", Long::class.java, user)
            "load_all", "search_by_query" -> {
                val keyword = if (operation == "search_by_query") " AND query ILIKE ?" else ""
                val params = mutableListOf<Any?>(user)
                if (keyword.isNotBlank()) params.add("%${args.path("keyword").asText()}%")
                params.add(limit(args, if (keyword.isBlank()) 100 else 50))
                val offset = if (keyword.isBlank()) args.path("offset").asInt(0) else 0
                if (offset < 0) throw ApiFailure(422, "조회 위치를 확인해주세요")
                params.add(offset)
                jdbc.queryForList("SELECT * FROM history WHERE user_id=?$keyword ORDER BY created DESC,id DESC LIMIT ? OFFSET ?", *params.toTypedArray()).map(::historyView)
            }
            "load_one" -> jdbc.queryForList("SELECT * FROM history WHERE user_id=? AND id=?", user, args.path("record_id").asLong()).firstOrNull()?.let { raw ->
                (row(raw).path("result") as ObjectNode).put("query", raw["query"].toString())
            }
            "delete_one" -> { jdbc.update("DELETE FROM history WHERE user_id=? AND id=?", user, args.path("record_id").asLong()); null }
            "delete_all" -> { jdbc.update("DELETE FROM history WHERE user_id=?", user); null }
            else -> throw ApiFailure(404, "시세 이력 저장 경로가 없습니다")
        }
    }
    fun activity(operation: String, args: JsonNode): Any? {
        val user = owner(args)
        if (operation !in setOf("save", "count_today", "delete_all") && user == null) throw ApiFailure(422, "활동 소유자가 필요합니다")
        return when (operation) {
            "save" -> jdbc.queryForObject("INSERT INTO activity(user_id,type,title,summary,meta,created) VALUES (?,?,?,?,?::json,?) RETURNING id",
                Long::class.java, user, args.path("type_").asText(), args.path("title").asText(), args.path("summary").asText(""),
                args.get("meta")?.takeUnless(JsonNode::isNull)?.toString() ?: "{}", now())
            "count_today" -> if (user == null) 0 else jdbc.queryForObject("SELECT count(*) FROM activity WHERE user_id=? AND type=? AND created LIKE ?",
                Long::class.java, user, args.path("type_").asText(), LocalDate.now().toString() + "%")
            "delete_all" -> { if (user != null) jdbc.update("DELETE FROM activity WHERE user_id=?", user); null }
            "load_recent" -> jdbc.queryForList("SELECT id,type,title,summary,meta,created FROM activity WHERE user_id=? ORDER BY created DESC,id DESC LIMIT ?",
                user, limit(args, 10)).map(::row)
            else -> throw ApiFailure(404, "활동 이력 저장 경로가 없습니다")
        }
    }
}
