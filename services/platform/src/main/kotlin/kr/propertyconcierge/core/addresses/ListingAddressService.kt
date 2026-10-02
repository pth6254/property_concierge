package kr.propertyconcierge.core.addresses

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.integrations.ExternalJsonClient
import kr.propertyconcierge.core.integrations.decodeDataGoKey
import org.springframework.core.env.Environment
import org.springframework.stereotype.Service
import java.nio.charset.StandardCharsets.UTF_8
import java.security.MessageDigest
import java.time.Instant
import java.util.Base64
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import javax.xml.XMLConstants
import javax.xml.parsers.DocumentBuilderFactory

data class ListingAddressValue(val roadAddress: String = "", val jibunAddress: String, val legalRegionCode: String,
    val latitude: Double, val longitude: Double, val buildingName: String = "", val nameSource: String,
    val nameStatus: String, val nameCandidates: List<String> = emptyList(), val source: String = "kakao_address",
    val checkedAt: String, val identityLevel: String, val parcelMainNo: String = "", val parcelSubNo: String = "", val parcelMountain: Boolean = false) {
    fun check() {
        require(jibunAddress.isNotBlank() && jibunAddress.length <= 500 && roadAddress.length <= 500)
        require(legalRegionCode.matches(Regex("[0-9]{10}")) && latitude.isFinite() && latitude in -90.0..90.0 && longitude.isFinite() && longitude in -180.0..180.0)
        require(buildingName.length <= 150 && nameCandidates.size <= 10 && nameCandidates.all { it.length <= 150 })
        require(nameSource in setOf("kakao_address", "building_register", "unknown") && nameStatus in setOf("found", "unknown", "ambiguous"))
        require(source == "kakao_address" && identityLevel in setOf("building", "parcel"))
        require(parcelMainNo.isEmpty() || parcelMainNo.matches(Regex("[0-9]{1,4}")))
        require(parcelSubNo.isEmpty() || parcelSubNo.matches(Regex("[0-9]{1,4}")))
    }
}
data class AddressProofInput(val token: String, val userId: Long)

@Service
class ListingAddressService(private val http: ExternalJsonClient, private val json: ObjectMapper, env: Environment) {
    private val key = env.getProperty("KAKAO_REST_API_KEY", "").trim()
    private val root = env.getProperty("KAKAO_API_ROOT", "https://dapi.kakao.com/v2/local/search/").trimEnd('/')
    private val molitKey = env.getProperty("MOLIT_API_KEY", "").trim()
    private val buildingUrl = env.getProperty("BUILDING_REGISTER_URL", "https://apis.data.go.kr/1613000/BldRgstHubService/getBrBasisOulnInfo")
    private val secret = env.getRequiredProperty("JWT_SECRET_KEY")
    private fun encode(value: ByteArray) = Base64.getUrlEncoder().withoutPadding().encodeToString(value)
    private fun signature(body: String): ByteArray = Mac.getInstance("HmacSHA256").run {
        init(SecretKeySpec(secret.toByteArray(UTF_8), "HmacSHA256")); doFinal(("listing-address-v1:" + body).toByteArray(UTF_8))
    }
    fun sign(address: ListingAddressValue, owner: Long): String {
        address.check(); require(owner > 0)
        val body = encode(json.writeValueAsBytes(mapOf("owner" to owner, "expires" to Instant.now().epochSecond + 3600, "address" to address)))
        return body + "." + encode(signature(body))
    }
    fun verify(token: String, owner: Long): ListingAddressValue {
        try {
            require(token.length <= 20000 && owner > 0)
            val parts = token.split('.'); require(parts.size == 2)
            require(MessageDigest.isEqual(signature(parts[0]), Base64.getUrlDecoder().decode(parts[1])))
            val body = json.readTree(Base64.getUrlDecoder().decode(parts[0]))
            require(body.path("owner").isIntegralNumber && body.path("owner").asLong() == owner && body.path("expires").isNumber
                && body.path("expires").asDouble() > Instant.now().toEpochMilli() / 1000.0)
            return json.treeToValue(body.path("address"), ListingAddressValue::class.java).also { it.check() }
        } catch (_: IllegalArgumentException) { throw ApiFailure(422, "주소 확인 정보가 유효하지 않거나 만료되었습니다. 주소를 다시 검색·선택해주세요.") }
        catch (_: com.fasterxml.jackson.core.JacksonException) { throw ApiFailure(422, "주소 확인 정보 형식을 확인해주세요") }
    }
    fun kakao(query: String, kind: String, size: Int = 5): JsonNode {
        if (key.isBlank()) throw ApiFailure(503, "주소 검색 설정이 없습니다. 주소를 직접 입력하거나 관리자에게 문의해주세요.")
        require(kind in setOf("keyword", "address"))
        return http.get("$root/$kind.json?" + http.form(mapOf("query" to query, "size" to size.toString())), mapOf("Authorization" to "KakaoAK $key"))
    }
    private fun names(address: JsonNode): List<String> {
        val code = address.path("b_code").asText(); val bun = address.path("main_address_no").asText(); val ji = address.path("sub_address_no").asText("0").ifBlank { "0" }
        if (molitKey.isBlank() || !code.matches(Regex("[0-9]{10}")) || bun.isBlank() || address.path("mountain_yn").asText() == "Y") return emptyList()
        return runCatching {
            val xml = http.text("GET", buildingUrl + "?" + http.form(mapOf("serviceKey" to decodeDataGoKey(molitKey),
                "sigunguCd" to code.take(5), "bjdongCd" to code.takeLast(5), "bun" to bun.padStart(4,'0'), "ji" to ji.padStart(4,'0'),
                "numOfRows" to "100", "pageNo" to "1", "_type" to "xml")))
            val factory = DocumentBuilderFactory.newInstance().apply {
                setFeature("http://apache.org/xml/features/disallow-doctype-decl", true)
                setAttribute(XMLConstants.ACCESS_EXTERNAL_DTD, ""); setAttribute(XMLConstants.ACCESS_EXTERNAL_SCHEMA, "")
            }
            val document = factory.newDocumentBuilder().parse(xml.byteInputStream())
            fun value(parent: org.w3c.dom.Element, field: String) = parent.getElementsByTagName(field).item(0)?.textContent?.trim() ?: ""
            val root = document.documentElement
            if (value(root, "resultCode").trimStart('0').isNotEmpty() || (value(root,"totalCount").toIntOrNull() ?: 0) > 100) return@runCatching emptyList<String>()
            val items = root.getElementsByTagName("item")
            (0 until items.length).mapNotNull { index ->
                val item = items.item(index) as org.w3c.dom.Element
                if (value(item,"sigunguCd") != code.take(5) || value(item,"bjdongCd") != code.takeLast(5)
                    || value(item,"bun").padStart(4,'0') != bun.padStart(4,'0') || value(item,"ji").ifBlank { "0" }.padStart(4,'0') != ji.padStart(4,'0')) null
                else value(item,"bldNm").takeIf { it.isNotBlank() && it.length <= 150 }
            }.distinct().sorted().take(10)
        }.getOrDefault(emptyList())
    }
    private fun normalize(document: JsonNode): ListingAddressValue? {
        val address = document.path("address"); val road = document.path("road_address")
        if (address.path("main_address_no").asText().isBlank() || !address.path("b_code").asText().matches(Regex("[0-9]{10}"))) return null
        return runCatching {
            var name = road.path("building_name").asText("").trim()
            val candidates = if (name.isBlank()) names(address) else emptyList()
            val source = if (name.isNotBlank()) "kakao_address" else if (candidates.size == 1) { name = candidates[0]; "building_register" } else "unknown"
            ListingAddressValue(road.path("address_name").asText(""), address.path("address_name").asText(), address.path("b_code").asText(),
                document.path("y").asText().toDouble(), document.path("x").asText().toDouble(), name, source,
                if (name.isNotBlank()) "found" else if (candidates.isNotEmpty()) "ambiguous" else "unknown", candidates,
                checkedAt=Instant.now().toString(), identityLevel=if (name.isNotBlank()) "building" else "parcel",
                parcelMainNo=address.path("main_address_no").asText(), parcelSubNo=address.path("sub_address_no").asText(),
                parcelMountain=address.path("mountain_yn").asText() == "Y").also { it.check() }
        }.getOrNull()
    }
    fun search(query: String, owner: Long): Map<String, Any> {
        if (query.trim().length !in 2..200) throw ApiFailure(422, "주소 또는 단지명을 두 글자 이상 입력해주세요.")
        val documents = kakao(query.trim(), "address").path("documents").toMutableList()
        if (documents.isEmpty()) {
            val addresses = kakao(query.trim(), "keyword").path("documents").map { it.path("road_address_name").asText("").ifBlank { it.path("address_name").asText("") } }.filter(String::isNotBlank).distinct().take(5)
            for (address in addresses) documents.addAll(kakao(address, "address").path("documents").toList())
        }
        val values = java.util.concurrent.Executors.newVirtualThreadPerTaskExecutor().use { pool ->
            documents.take(10).map { document -> pool.submit<ListingAddressValue?> { normalize(document) } }.mapNotNull { it.get() }
        }.distinctBy { listOf(it.legalRegionCode, it.jibunAddress, it.roadAddress, it.buildingName) }
        return mapOf("items" to values.map { value -> json.valueToTree<com.fasterxml.jackson.databind.node.ObjectNode>(value).put("token", sign(value, owner)) })
    }
}
