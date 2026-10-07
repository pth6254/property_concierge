package kr.propertyconcierge.core.addresses

import com.fasterxml.jackson.databind.JsonNode
import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.integrations.ExternalJsonClient
import org.springframework.core.env.Environment
import org.springframework.stereotype.Service
import java.math.BigDecimal
import java.math.RoundingMode
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.util.concurrent.Executors

data class LandLookupInput(val address: String, val asOfDate: String = "")

@Service
class LandInformationService(private val addresses: ListingAddressService, private val http: ExternalJsonClient, env: Environment) {
    private val key = env.getProperty("VWORLD_API_KEY", "").trim()
    private val domain = env.getProperty("VWORLD_DOMAIN", "localhost")
    private val root = env.getProperty("VWORLD_NED_ROOT", "https://api.vworld.kr/ned/data").trimEnd('/')
    private data class Source(val id: String, val endpoint: String, val wrapper: String, val title: String, val url: String, val annual: Boolean)
    private val sources = listOf(
        Source("register", "ladfrlList", "ladfrlVOList", "국토교통부 토지임야정보", "https://www.data.go.kr/data/15123884/openapi.do", false),
        Source("characteristics", "getLandCharacteristics", "landCharacteristicss", "국토교통부 토지특성정보", "https://www.data.go.kr/data/15123549/openapi.do", true),
        Source("official_price", "getIndvdLandPriceAttr", "indvdLandPrices", "국토교통부 개별공시지가정보", "https://www.data.go.kr/data/15124014/openapi.do", true),
        Source("land_use", "getLandUseAttr", "landUses", "국토교통부 토지이용계획정보", "https://www.data.go.kr/data/15045900/fileData.do", false),
    )
    private data class Observed(val source: Source, val status: String, val rows: List<JsonNode> = emptyList())
    private fun fetch(source: Source, pnu: String, asOf: LocalDate): Observed {
        if (key.isBlank()) return Observed(source, "not_configured")
        return try {
            val response = http.get("$root/${source.endpoint}?" + http.form(mapOf("key" to key, "domain" to domain,
                "pnu" to pnu, "format" to "json", "numOfRows" to "100", "pageNo" to "1")))
            val body = response.path(source.wrapper)
            val code = body.path("resultCode").asText("")
            if (code == "EXPIRE_KEY") return Observed(source, "key_expired")
            if (!body.isObject || code !in setOf("", "00", "000", "0", "SUCCESS")) return Observed(source, "provider_error")
            val fields = body.path(if (source.id == "register") "ladfrlVOList" else "field")
            val rows = when { fields.isArray -> fields.toList(); fields.isObject -> listOf(fields); else -> emptyList() }
            val count = body.path("totalCount").asText().toIntOrNull() ?: return Observed(source, "invalid_response")
            if (count > 100 || rows.size != count) return Observed(source, "incomplete")
            if (rows.any { !it.isObject || it.path("pnu").asText() != pnu }) return Observed(source, "parcel_mismatch")
            val eligible = if (source.annual) rows.filter {
                val year = it.path("stdrYear").asText().toIntOrNull()
                val month = it.path("stdrMt").asText("01").toIntOrNull()
                year != null && month != null && month in 1..12 && year >= 1900 &&
                    (year < asOf.year || year == asOf.year && month <= asOf.monthValue)
            } else rows
            if (eligible.isEmpty()) return Observed(source, if (rows.isEmpty()) "not_found" else "no_dated_record")
            val selected = if (source.annual) {
                val newest = eligible.maxOf { it.path("stdrYear").asText() + it.path("stdrMt").asText("01").padStart(2, '0') }
                eligible.filter { it.path("stdrYear").asText() + it.path("stdrMt").asText("01").padStart(2, '0') == newest }.distinct()
            } else eligible.distinct()
            if ((source.annual || source.id == "register") && selected.size != 1) Observed(source, "ambiguous") else Observed(source, "found", selected)
        } catch (_: Exception) {
            // 공급자 오류에는 키가 포함된 요청 URL이 붙을 수 있어 응답·로그로 전달하지 않는다.
            Observed(source, "request_error")
        }
    }
    fun lookup(input: LandLookupInput): Map<String, Any?> {
        val today = LocalDate.now(ZoneId.of("Asia/Seoul"))
        val asOf = if (input.asOfDate.isBlank()) today else try { LocalDate.parse(input.asOfDate) }
            catch (_: Exception) { throw ApiFailure(422, "조회 기준일을 확인해주세요") }
        if (asOf.isAfter(today)) throw ApiFailure(422, "미래 기준일의 토지 정보는 조회할 수 없습니다")
        val address = addresses.parcel(input.address)
        val pnu = address.legalRegionCode + (if (address.parcelMountain) "2" else "1") + address.parcelMainNo.padStart(4, '0') + address.parcelSubNo.ifBlank { "0" }.padStart(4, '0')
        val checked = Instant.now().toString()
        val observations = Executors.newVirtualThreadPerTaskExecutor().use { pool ->
            sources.map { source -> pool.submit<Observed> { fetch(source, pnu, asOf) } }.map { it.get() }
        }
        val characteristics = observations.single { it.source.id == "characteristics" }.rows.singleOrNull()
        val register = observations.single { it.source.id == "register" }.rows.singleOrNull()
        val price = observations.single { it.source.id == "official_price" }.rows.singleOrNull()
        fun text(row: JsonNode?, field: String) = row?.path(field)?.asText()?.trim()?.takeIf { it.isNotBlank() && it.length <= 200 }
        fun number(row: JsonNode?, field: String) = text(row, field)?.toBigDecimalOrNull()?.takeIf { it > BigDecimal.ZERO && it <= BigDecimal("1000000000000000") }
        val area = number(register, "lndpclAr")
        val referenceArea = number(characteristics, "lndpclAr")
        val unitPrice = number(price, "pblntfPclnd")
        val sameYear = text(characteristics, "stdrYear") != null && text(characteristics, "stdrYear") == text(price, "stdrYear")
        val fields = linkedMapOf<String, Any?>(
            "land_area_sqm" to area, "land_category" to text(register, "lndcgrCodeNm"),
            "actual_use" to text(characteristics, "ladUseSittnNm"), "terrain_height" to text(characteristics, "tpgrphHgCodeNm"),
            "terrain_shape" to text(characteristics, "tpgrphFrmCodeNm"), "road_frontage" to text(characteristics, "roadSideCodeNm"),
            "zone_primary" to text(characteristics, "prposArea1Nm"), "zone_secondary" to text(characteristics, "prposArea2Nm"),
            "official_price_won_per_sqm" to unitPrice,
        )
        val total = if (sameYear && referenceArea != null && unitPrice != null) runCatching { referenceArea.multiply(unitPrice).setScale(0, RoundingMode.HALF_EVEN).longValueExact() }.getOrNull() else null
        return mapOf("schema_version" to "land-information-1.0", "result_kind" to "public_reference", "pnu" to pnu,
            "address" to address.jibunAddress, "road_address" to address.roadAddress, "scope" to "single_parcel",
            "requested_as_of" to asOf.toString(), "checked_at" to checked,
            "status" to if (observations.all { it.status == "found" } && fields.values.none { it == null }) "found" else if (observations.any { it.status == "found" }) "partial" else "unavailable",
            "fields" to fields, "official_reference_total_won" to total,
            "official_reference_area_sqm" to referenceArea,
            "characteristics_year" to text(characteristics, "stdrYear"), "official_price_year" to text(price, "stdrYear"),
            "land_use" to observations.single { it.source.id == "land_use" }.rows.map { row ->
                mapOf("name" to text(row, "prposAreaDstrcCodeNm"), "conflict" to text(row, "cnflcAtNm"), "record_updated_at" to text(row, "lastUpdtDt"))
            },
            "sources" to observations.map { o -> mapOf("id" to o.source.id, "title" to o.source.title, "url" to o.source.url,
                "status" to o.status, "checked_at" to checked, "records" to o.rows.size,
                "reference_year" to o.rows.firstOrNull()?.let { text(it, "stdrYear") },
                "record_updated_at" to o.rows.firstOrNull()?.let { text(it, "lastUpdtDt") }) },
            "missing_fields" to fields.filterValues { it == null }.keys.toList(),
            "limitations" to listOfNotNull("선택 주소의 한 필지 공개정보입니다. 여러 필지의 합계·지분·현장 상태는 별도 확인해야 합니다.",
                "공시지가와 공시지가×면적은 시장 시세·감정평가액이 아닙니다. 도로접면 정보만으로 실제 통행·건축 허가 가능성을 확정하지 않습니다.",
                "자료 기준연도와 조회 시각을 구분합니다. 과거 기준일 당시 공개되어 있던 자료를 재현한 결과는 아닙니다.",
                if (!sameYear && area != null && unitPrice != null) "면적과 공시지가의 기준연도가 달라 공시 참고 총액을 보류했습니다." else null,
                if (observations.any { it.status == "key_expired" }) "VWorld API 키가 만료되어 자료 조회를 완료하지 못했습니다. 관리자 설정 갱신이 필요합니다." else null,
            ))
    }
}
