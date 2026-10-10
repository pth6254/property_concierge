package kr.propertyconcierge.core.listings

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import com.fasterxml.jackson.databind.node.ObjectNode
import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.bridge.PythonClient
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.stereotype.Service
import org.springframework.transaction.support.TransactionTemplate
import java.time.Instant

data class ListingFilters(val regionCode: String?, val propertyType: String?, val transactionType: String?,
    val status: String?, val budgetMax: Long?, val areaMin: Double?, val freshOnly: Boolean, val page: Int, val pageSize: Int)

@Service
class ListingService(private val jdbc: JdbcTemplate, private val json: ObjectMapper,
    private val python: PythonClient, private val transaction: TransactionTemplate) {
    private val staleSeconds = 7 * 86400
    private val types = setOf("apartment", "officetel", "row_house", "detached", "non_residential", "industrial", "land")
    private fun now() = System.currentTimeMillis() / 1000.0
    private fun payload(row: Map<String, Any?>): ObjectNode = json.readTree(row["payload"].toString()) as ObjectNode
    private fun number(row: Map<String, Any?>, key: String) = (row[key] as? Number)?.toDouble()
    private fun view(row: Map<String, Any?>): ObjectNode {
        val result = payload(row)
        if (!result.has("alias")) result.put("alias", "")
        if (!result.has("address_details")) result.putNull("address_details")
        result.put("id", (row["id"] as Number).toLong()); result.put("source_name", row["source_name"].toString())
        val confirmed = requireNotNull(number(row, "confirmed_at"))
        val fetched = number(row, "last_collection_at")
        result.put("needs_confirmation", confirmed < now() - staleSeconds || (fetched != null && fetched > confirmed))
        for (key in listOf("first_seen_at", "last_seen_at", "last_collection_at")) {
            val value = number(row, key); if (value == null) result.putNull(key) else result.put(key, value)
        }
        row["last_collection_outcome"]?.let { result.put("last_collection_outcome", it.toString()) }
            ?: result.putNull("last_collection_outcome")
        result.put("region_linked", row["legal_region_code"] != null)
        return result
    }
    // 페이지 안의 자료에만 관측값을 붙여 전체 매물·관측 이력을 메모리에 올리지 않는다.
    private val observed = """
        LEFT JOIN LATERAL (
          SELECT substring(i.payload->>'source_url' from '/articles/([0-9]+)') AS article
          WHERE i.payload->>'source_url' ~ '^https://(land|new.land|fin.land|m.land)\.naver\.com/'
          UNION ALL SELECT substring(i.payload->>'source_url' from '[?&]articleNo=([0-9]+)')
          WHERE i.payload->>'source_url' ~ '^https://(land|new.land|fin.land|m.land)\.naver\.com/'
            AND i.payload->>'source_url' !~ '/articles/[0-9]+'
        ) source ON true
        LEFT JOIN LATERAL (SELECT fetched_at AS last_collection_at, outcome AS last_collection_outcome
          FROM listing_observations WHERE user_id=i.user_id AND external_id=source.article
          ORDER BY fetched_at DESC,id DESC LIMIT 1) latest ON true
        LEFT JOIN LATERAL (SELECT min(fetched_at) AS first_seen_at,max(fetched_at) AS last_seen_at
          FROM listing_observations WHERE user_id=i.user_id AND external_id=source.article AND outcome='observed') seen ON true
    """.trimIndent()

    fun search(owner: Long, filters: ListingFilters): Map<String, Any?> {
        if (filters.page !in 1..100000 || filters.pageSize !in 1..100 ||
            filters.propertyType?.let { it !in types } == true ||
            filters.transactionType?.let { it !in setOf("purchase", "lease", "rent") } == true ||
            filters.status?.let { it !in setOf("active", "withdrawn", "completed", "unknown") } == true ||
            filters.budgetMax?.let { it < 0 || it > 1_000_000_000_000_000L } == true ||
            filters.areaMin?.let { !it.isFinite() || it < 0 || it > 100000000 } == true)
            throw ApiFailure(422, "매물 검색 조건을 확인해주세요")
        val conditions = mutableListOf("i.user_id=?"); val values = mutableListOf<Any>(owner)
        filters.regionCode?.let { code ->
            if (!code.matches(Regex("[0-9]{10}"))) throw ApiFailure(422, "법정동 코드 형식을 확인해주세요")
            val region = jdbc.queryForList("SELECT code,level FROM legal_regions WHERE code=? AND is_active=true", code).firstOrNull()
                ?: throw ApiFailure(404, "선택한 지역을 찾을 수 없습니다")
            val length = mapOf("sido" to 2, "sigungu" to 5, "eup_myeon_dong" to 10)[region["level"]]
                ?: throw ApiFailure(422, "시·도, 시·군·구, 읍·면·동을 선택해주세요")
            conditions.add("i.legal_region_code LIKE ?"); values.add(code.take(length) + "%")
        }
        fun condition(column: String, value: Any?, operator: String = "=") {
            if (value != null) { conditions.add("i.$column $operator ?"); values.add(value) }
        }
        condition("property_type", filters.propertyType); condition("transaction_type", filters.transactionType)
        condition("status", filters.status); condition("price", filters.budgetMax, "<="); condition("area_sqm", filters.areaMin, ">=")
        if (filters.freshOnly) {
            conditions.add("i.confirmed_at>=?"); values.add(now() - staleSeconds); conditions.add("i.status='active'")
            conditions.add("""NOT EXISTS (SELECT 1 FROM listing_observations o WHERE o.user_id=i.user_id
              AND i.payload->>'source_url' ~ '^https://(land|new.land|fin.land|m.land)\.naver\.com/'
              AND o.external_id=coalesce(substring(i.payload->>'source_url' from '/articles/([0-9]+)'),
                substring(i.payload->>'source_url' from '[?&]articleNo=([0-9]+)')) AND o.fetched_at>i.confirmed_at)""")
        }
        val where = conditions.joinToString(" AND ")
        val count = jdbc.queryForObject("SELECT count(*) FROM imported_listings i WHERE $where", Long::class.java, *values.toTypedArray())
        val params = values + listOf(filters.pageSize, (filters.page - 1) * filters.pageSize)
        val rows = jdbc.queryForList("""SELECT i.*,latest.*,seen.* FROM
            (SELECT i.* FROM imported_listings i WHERE $where ORDER BY confirmed_at DESC,id DESC LIMIT ? OFFSET ?) i
            $observed ORDER BY i.confirmed_at DESC,i.id DESC""", *params.toTypedArray())
        return mapOf("items" to rows.map(::view), "total" to count, "page" to filters.page, "page_size" to filters.pageSize)
    }
    fun get(owner: Long, id: Long): ObjectNode {
        val row = jdbc.queryForList("SELECT i.*,latest.*,seen.* FROM imported_listings i $observed WHERE i.user_id=? AND i.id=?", owner, id).firstOrNull()
            ?: throw ApiFailure(404, "매물을 찾을 수 없습니다")
        return view(row)
    }
    fun history(owner: Long, id: Long): Map<String, Any> {
        get(owner, id)
        val rows = jdbc.queryForList("""SELECT r.payload,r.imported_at FROM listing_revisions r JOIN imported_listings i ON i.id=r.listing_id
            WHERE i.user_id=? AND i.id=? ORDER BY r.id DESC LIMIT 100""", owner, id)
        return mapOf("items" to rows.map { payload(it).put("imported_at", Instant.ofEpochMilli(((it["imported_at"] as Number).toDouble()*1000).toLong()).toString()) })
    }
    private val naverHost = Regex("""^https://(land|new\.land|fin\.land|m\.land)\.naver\.com/""")
    private fun article(url: String?): String? {
        if (url == null || !naverHost.containsMatchIn(url)) return null
        return Regex("""/articles/([0-9]+)""").find(url)?.groupValues?.get(1) ?: Regex("""[?&]articleNo=([0-9]+)""").find(url)?.groupValues?.get(1)
    }
    /** 저장된 확인값과 원문 수집 시도를 나눠 보여준다. 조회 중 외부 호출이나 상태 변경은 하지 않는다. */
    fun timeline(owner: Long, id: Long): JsonNode {
        val current = get(owner, id)
        val revisions = jdbc.queryForList("""SELECT r.payload,r.imported_at FROM listing_revisions r JOIN imported_listings i ON i.id=r.listing_id
            WHERE i.user_id=? AND i.id=? ORDER BY r.id ASC LIMIT 500""", owner, id)
            .map { (it["imported_at"] as Number).toDouble() to (json.readTree(it["payload"].toString()) as JsonNode) }
        val articleNo = article(current.path("source_url").asText(null))
        val observations = if (articleNo == null) emptyList() else
            jdbc.queryForList("SELECT fetched_at,outcome,payload FROM listing_observations WHERE user_id=? AND external_id=? ORDER BY fetched_at DESC,id DESC LIMIT 200", owner, articleNo)
                .map { Triple((it["fetched_at"] as Number).toDouble(), it["outcome"].toString(), json.readTree(it["payload"].toString()) as JsonNode) }
        return ListingTimeline(json).build(id, revisions, observations, current.path("needs_confirmation").asBoolean(false))
    }
    /** 호가 이력에 겹쳐 볼 저장 실거래와 저장된 AVM 결과. 조회에서 분석 실행·저장·후보 상태 변경은 하지 않는다. */
    fun marketOverlay(owner: Long, id: Long): JsonNode {
        val listing = get(owner, id)
        val applicable = listing.path("transaction_type").asText() == "purchase" && listing.path("property_type").asText() == "apartment" &&
            listing.path("area_basis").asText() == "exclusive" && listing.path("legal_region_code").asText("").length == 10
        // 외부 분석 호출은 DB 조회 밖에서 끝낸다. 실패해도 AVM 저장값과 호가 이력은 계속 보여준다.
        val trades = if (!applicable) null else try {
            python.analyze("data/listing-trades", mapOf("legal_region_code" to listing.path("legal_region_code").asText(),
                "name" to listing.path("name").asText(), "area_sqm" to listing.path("area_sqm").asDouble()))
        } catch (_: ApiFailure) {
            json.createObjectNode().put("available", false).put("reason", "실거래 조회 서비스에 연결하지 못했습니다").also { it.putArray("trades") }
        }
        val analyses = jdbc.queryForList("""SELECT a.property_id,a.case_id,a.status,a.analyzed_at,a.summary FROM candidate_analyses a
            JOIN case_properties p ON p.id=a.property_id JOIN purchase_cases c ON c.id=p.case_id
            WHERE c.user_id=? AND p.source_listing_id=? AND a.analysis_type='appraisal' ORDER BY a.analyzed_at DESC NULLS LAST LIMIT 5""", owner, id)
            .map { OverlayAnalysis((it["property_id"] as Number).toLong(), (it["case_id"] as Number).toLong(), it["status"].toString(),
                it["analyzed_at"]?.toString(), json.readTree(it["summary"].toString())) }
        return ListingMarketOverlay(json).build(listing, trades, analyses)
    }
    fun import(owner: Long, source: String, csv: String, commit: Boolean): JsonNode {
        if (source.isBlank() || source.length > 100 || source.contains('\u0000') || csv.isBlank() || csv.length > 1_000_000)
            throw ApiFailure(422, "출처와 CSV 입력을 확인해주세요")
        val regions = jdbc.queryForList("SELECT code,full_name FROM legal_regions WHERE is_active=true AND level='eup_myeon_dong'")
        // 외부 분석 호출은 DB 트랜잭션 밖에서 끝내고, 검증된 행 전체를 한 번에 저장한다.
        val checked = python.analyze("listing-import/validate", mapOf("user_id" to owner, "source_name" to source.trim(), "csv_text" to csv, "regions" to regions))
        val output = checked.path("validation") as? ObjectNode ?: throw ApiFailure(502, "매물 검증 응답 형식이 올바르지 않습니다")
        // Python 정수에는 64비트 상한이 없다. asLong 변환으로 금액이 조용히 바뀌지 않게 한다.
        for (entry in checked.path("rows")) {
            for (field in listOf("asking_price", "deposit", "monthly_rent")) {
                val value = entry.path("payload").get(field) ?: continue
                if (!value.isNull && (!value.isIntegralNumber || !value.canConvertToLong() || value.asLong() < 0))
                    throw ApiFailure(422, "${entry.path("row").asInt()}행: 금액은 원 단위 64비트 양수 정수 범위여야 합니다")
            }
        }
        if (!commit || !output.path("valid").asBoolean()) return output
        return requireNotNull(transaction.execute {
            jdbc.queryForList("SELECT pg_advisory_xact_lock(hashtext(?))", "listing-import:$owner:${source.trim()}")
            fun increment(key: String) { output.put(key, output.path(key).asInt() + 1) }
            for (entry in checked.path("rows")) {
                val data = entry.path("payload") as ObjectNode
                val confirmed = entry.path("confirmed_at").asDouble()
                val existing = jdbc.queryForList("SELECT * FROM imported_listings WHERE user_id=? AND source_name=? AND external_id=? FOR UPDATE",
                    owner, source.trim(), data.path("external_id").asText()).firstOrNull()
                if (existing != null && confirmed < requireNotNull(number(existing, "confirmed_at"))) { increment("skipped_older"); continue }
                val normalized = data.deepCopy().apply { if (path("alias").asText().isBlank()) remove("alias") }
                val old = existing?.let(::payload)?.apply { if (path("alias").asText().isBlank()) remove("alias") }
                if (old == normalized) { increment("unchanged"); continue }
                if (existing != null && confirmed == number(existing, "confirmed_at"))
                    throw ApiFailure(409, "${entry.path("row").asInt()}행: 같은 확인 시각의 내용이 다릅니다. 정확한 확인 시각을 입력해주세요")
                val code = data.get("legal_region_code")?.takeUnless(JsonNode::isNull)?.asText()
                val content = json.writeValueAsString(data)
                val params = arrayOf(code, data.path("property_type").asText(), data.path("transaction_type").asText(),
                    data.path("status").asText(), entry.path("price").asLong(), data.path("area_sqm").asDouble(), confirmed, content)
                val id = if (existing == null) {
                    jdbc.queryForObject("""INSERT INTO imported_listings(user_id,source_name,external_id,legal_region_code,property_type,
                        transaction_type,status,price,area_sqm,confirmed_at,payload) VALUES (?,?,?,?,?,?,?,?,?,?,?::json) RETURNING id""",
                        Long::class.java, owner, source.trim(), data.path("external_id").asText(), *params)
                } else {
                    jdbc.update("""UPDATE imported_listings SET legal_region_code=?,property_type=?,transaction_type=?,status=?,price=?,
                        area_sqm=?,confirmed_at=?,payload=?::json WHERE id=? AND user_id=?""", *params, existing["id"], owner)
                    (existing["id"] as Number).toLong()
                }
                jdbc.update("INSERT INTO listing_revisions(listing_id,imported_at,payload) VALUES (?,?,?::json)", id, now(), content)
                increment(if (existing == null) "created" else "updated")
            }
            output.put("committed", true)
        })
    }
}
