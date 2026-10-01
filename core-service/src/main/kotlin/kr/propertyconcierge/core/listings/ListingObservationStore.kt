package kr.propertyconcierge.core.listings

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import com.fasterxml.jackson.databind.node.ObjectNode
import kr.propertyconcierge.core.ApiFailure
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.stereotype.Service
import java.net.URI
import java.net.URLDecoder
import java.nio.charset.StandardCharsets.UTF_8

@Service
class ListingObservationStore(private val jdbc: JdbcTemplate, private val json: ObjectMapper) {
    private fun view(raw: Map<String, Any?>): ObjectNode = (json.readTree(raw["payload"].toString()) as ObjectNode).put("observation_id", (raw["id"] as Number).toLong())
    private fun article(url: String): String {
        val uri = try { URI(url) } catch (_: java.net.URISyntaxException) { throw ApiFailure(422, "개별 매물 링크 형식을 확인해주세요") }
        if (uri.scheme != "https" || uri.host !in setOf("land.naver.com", "new.land.naver.com", "fin.land.naver.com", "m.land.naver.com") || uri.userInfo != null || uri.port != -1)
            throw ApiFailure(422, "네이버 부동산 개별 매물 HTTPS 링크가 필요합니다")
        val matched = Regex("/articles/([0-9]{1,30})/?").matchEntire(uri.path)?.groupValues?.get(1)
        val ids = uri.rawQuery?.split('&')?.map { it.split('=', limit=2) }?.filter { URLDecoder.decode(it[0], UTF_8) == "articleNo" }
            ?.map { URLDecoder.decode(it.getOrElse(1) { "" }, UTF_8) } ?: emptyList()
        val value = matched ?: ids.singleOrNull()
        if (value == null || !value.matches(Regex("[0-9]{1,30}"))) throw ApiFailure(422, "네이버 부동산 개별 매물 HTTPS 링크가 필요합니다")
        return value
    }
    fun dispatch(operation: String, args: JsonNode): Any? {
        val owner = args.path("user_id").asLong()
        if (owner <= 0) throw ApiFailure(422, "매물 관측 소유자가 필요합니다")
        return when (operation) {
            "record_observation" -> {
                val result = args.path("result")
                val job = args.get("job_id")?.takeUnless(JsonNode::isNull)?.asText()?.takeIf(String::isNotBlank)
                val id = jdbc.queryForObject("""INSERT INTO listing_observations(user_id,job_id,external_id,requested_at,fetched_at,outcome,payload)
                    VALUES (?,?,?,?,?,?,?::json) ON CONFLICT(job_id) DO UPDATE SET job_id=excluded.job_id
                    WHERE listing_observations.user_id=excluded.user_id RETURNING id""", Long::class.java,
                    owner, job, result.path("external_id").asText(), result.path("requested_at").asDouble(), result.path("fetched_at").asDouble(),
                    result.path("outcome").asText(), result.toString()) ?: throw ApiFailure(409, "수집 작업의 소유자가 일치하지 않습니다")
                view(jdbc.queryForList("SELECT id,payload FROM listing_observations WHERE id=? AND user_id=?", id, owner).first())
            }
            "history" -> mapOf("items" to jdbc.queryForList("SELECT id,payload FROM listing_observations WHERE user_id=? AND external_id=? ORDER BY fetched_at DESC,id DESC LIMIT 100",
                owner, article(args.path("url").asText())).map(::view))
            "get_observation" -> jdbc.queryForList("SELECT id,payload FROM listing_observations WHERE user_id=? AND id=?", owner, args.path("observation_id").asLong()).firstOrNull()?.let(::view)
                ?: throw ApiFailure(404, "수집 기록을 찾을 수 없습니다")
            else -> throw ApiFailure(404, "매물 관측 저장 경로가 없습니다")
        }
    }
}
