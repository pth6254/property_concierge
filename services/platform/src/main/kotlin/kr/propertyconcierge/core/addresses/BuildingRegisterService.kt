package kr.propertyconcierge.core.addresses

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.integrations.ExternalJsonClient
import kr.propertyconcierge.core.integrations.decodeDataGoKey
import org.springframework.core.env.Environment
import org.springframework.data.redis.core.StringRedisTemplate
import org.springframework.stereotype.Service
import java.math.BigDecimal
import java.nio.charset.StandardCharsets.UTF_8
import java.security.MessageDigest
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Base64
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import javax.xml.XMLConstants
import javax.xml.parsers.DocumentBuilderFactory

data class BuildingLookupInput(val addressToken: String, val buildingId: String = "", val buildingDong: String = "",
    val unitNumber: String = "", val propertyType: String = "apartment")
data class BuildingProofInput(val token: String, val userId: Long, val addressToken: String,
    val buildingDong: String = "", val unitNumber: String = "", val areaSqm: Double, val areaBasis: String, val floor: String = "")

@Service
class BuildingRegisterService(private val addresses: ListingAddressService, private val http: ExternalJsonClient,
    private val json: ObjectMapper, private val redis: StringRedisTemplate, env: Environment) {
    private val key = env.getProperty("MOLIT_API_KEY", "").trim()
    private val root = env.getProperty("BUILDING_REGISTER_API_ROOT", "https://apis.data.go.kr/1613000/BldRgstHubService").trimEnd('/')
    private val secret = env.getRequiredProperty("JWT_SECRET_KEY")
    private val types = setOf("apartment", "officetel", "row_house", "detached", "non_residential", "industrial", "land")
    private val endpoints = setOf("getBrTitleInfo", "getBrRecapTitleInfo", "getBrFlrOulnInfo", "getBrExposPubuseAreaInfo", "getBrJijiguInfo", "getBrWclfInfo")
    private data class Page(val items: List<Map<String, String>>, val complete: Boolean, val checkedAt: String)
    private fun encoded(bytes: ByteArray) = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)
    private fun signature(body: String) = Mac.getInstance("HmacSHA256").run {
        init(SecretKeySpec(secret.toByteArray(UTF_8), "HmacSHA256")); doFinal(("building-register-v1:" + body).toByteArray(UTF_8))
    }
    private fun reference(value: String, suffix: String) = value.trim().replace(Regex("\\s+"), "").removeSuffix(suffix).uppercase()
    private fun parcel(address: ListingAddressValue) = listOf(address.legalRegionCode, address.parcelMainNo.padStart(4, '0'),
        address.parcelSubNo.ifBlank { "0" }.padStart(4, '0'), address.parcelMountain.toString()).joinToString(":")
    private fun matches(item: Map<String, String>, address: ListingAddressValue): Boolean =
        item["sigunguCd"] == address.legalRegionCode.take(5) && item["bjdongCd"] == address.legalRegionCode.takeLast(5) &&
        item["bun"].orEmpty().padStart(4, '0') == address.parcelMainNo.padStart(4, '0') &&
        item["ji"].orEmpty().ifBlank { "0" }.padStart(4, '0') == address.parcelSubNo.ifBlank { "0" }.padStart(4, '0') &&
        item["platGbCd"].orEmpty().ifBlank { "0" } == if (address.parcelMountain) "1" else "0"

    // 공급자 페이지 순서·응답 필터를 신뢰하지 않고 필지와 범위를 다시 검증한다.
    private fun read(endpoint: String, address: ListingAddressValue, extra: Map<String, String> = emptyMap()): Page {
        require(endpoint in endpoints)
        val params = mapOf("sigunguCd" to address.legalRegionCode.take(5), "bjdongCd" to address.legalRegionCode.takeLast(5),
            "bun" to address.parcelMainNo.padStart(4, '0'), "ji" to address.parcelSubNo.ifBlank { "0" }.padStart(4, '0'),
            "platGbCd" to if (address.parcelMountain) "1" else "0") + extra
        val digest = MessageDigest.getInstance("SHA-256").digest((root + endpoint + json.writeValueAsString(params)).toByteArray(UTF_8))
        val cacheKey = "building-register:v1:" + encoded(digest)
        runCatching { redis.opsForValue().get(cacheKey) }.getOrNull()?.let { saved ->
            runCatching {
                val node = json.readTree(saved)
                Page(node.path("items").map { item -> item.fields().asSequence().associate { it.key to it.value.asText() } },
                    node.path("complete").asBoolean(), node.path("checked_at").asText())
            }.getOrNull()?.let { return it }
        }
        val all = mutableListOf<Map<String, String>>()
        var complete = false
        for (page in 1..5) {
            val xml = http.text("GET", "$root/$endpoint?" + http.form(params + mapOf("serviceKey" to decodeDataGoKey(key),
                "numOfRows" to "100", "pageNo" to page.toString(), "_type" to "xml")))
            val factory = DocumentBuilderFactory.newInstance().apply {
                setFeature("http://apache.org/xml/features/disallow-doctype-decl", true)
                setFeature("http://xml.org/sax/features/external-general-entities", false)
                setFeature("http://xml.org/sax/features/external-parameter-entities", false)
                setAttribute(XMLConstants.ACCESS_EXTERNAL_DTD, ""); setAttribute(XMLConstants.ACCESS_EXTERNAL_SCHEMA, "")
            }
            val document = factory.newDocumentBuilder().parse(xml.byteInputStream()).documentElement
            fun text(name: String) = document.getElementsByTagName(name).item(0)?.textContent?.trim().orEmpty()
            if (text("resultCode") !in setOf("00", "0")) throw ApiFailure(502, "건축물대장 조회를 완료하지 못했습니다. 직접 입력은 계속 사용할 수 있습니다.")
            val total = text("totalCount").toIntOrNull()?.takeIf { it >= 0 } ?: throw ApiFailure(502, "건축물대장 응답 범위를 확인하지 못했습니다")
            val elements = document.getElementsByTagName("item")
            val records = (0 until elements.length).map { index ->
                val element = elements.item(index)
                (0 until element.childNodes.length).map { element.childNodes.item(it) }.filter { it.nodeType == org.w3c.dom.Node.ELEMENT_NODE }
                    .associate { it.nodeName to it.textContent.trim() }
            }
            all.addAll(records.filter { matches(it, address) })
            if (page * 100 >= total) { complete = true; break }
            if (records.isEmpty()) break
        }
        val result = Page(all, complete, Instant.now().toString())
        runCatching { redis.opsForValue().set(cacheKey, json.writeValueAsString(mapOf("items" to result.items,
            "complete" to complete, "checked_at" to result.checkedAt)), Duration.ofMinutes(15)) }
        return result
    }
    private fun decimal(item: Map<String, String>, field: String, positive: Boolean = false): BigDecimal? =
        item[field]?.toBigDecimalOrNull()?.takeIf { it >= BigDecimal.ZERO && it <= BigDecimal("100000000") && (!positive || it > BigDecimal.ZERO) }
    private fun date(item: Map<String, String>, field: String): String? = runCatching {
        LocalDate.parse(item[field], DateTimeFormatter.BASIC_ISO_DATE).toString()
    }.getOrNull()
    private fun floorName(item: Map<String, String>): String = item["flrNoNm"].orEmpty().ifBlank {
        item["flrNo"].orEmpty().takeIf { it.isNotBlank() }?.let { (if (item["flrGbCd"] == "10") "지하" else "") + it + "층" }.orEmpty()
    }
    private fun fields(item: Map<String, String>): Map<String, Any?> {
        val numbers = mapOf("land_area_sqm" to "platArea", "building_area_sqm" to "archArea", "total_area_sqm" to "totArea",
            "far_area_sqm" to "vlRatEstmTotArea", "building_coverage_pct" to "bcRat", "floor_area_ratio_pct" to "vlRat",
            "height_m" to "heit", "above_ground_floors" to "grndFlrCnt", "underground_floors" to "ugrndFlrCnt",
            "households" to "hhldCnt", "families" to "fmlyCnt", "unit_count" to "hoCnt", "main_buildings" to "mainBldCnt",
            "auxiliary_buildings" to "atchBldCnt", "auxiliary_area_sqm" to "atchBldArea", "total_parking" to "totPkngCnt",
            "indoor_mechanical_parking" to "indrMechUtcnt", "outdoor_mechanical_parking" to "oudrMechUtcnt",
            "indoor_self_parking" to "indrAutoUtcnt", "outdoor_self_parking" to "oudrAutoUtcnt",
            "passenger_elevators" to "rideUseElvtCnt", "emergency_elevators" to "emgenUseElvtCnt", "energy_saving_pct" to "engrRat", "epi_score" to "engrEpi")
        return numbers.mapValues { (name, field) -> decimal(item, field, name.endsWith("area_sqm") || name == "height_m") } + mapOf(
            "use" to item["mainPurpsCdNm"].orEmpty().ifBlank { item["etcPurps"].orEmpty() }, "other_use" to item["etcPurps"].orEmpty(),
            "structure" to item["strctCdNm"].orEmpty().ifBlank { item["etcStrct"].orEmpty() }, "roof" to item["roofCdNm"].orEmpty().ifBlank { item["etcRoof"].orEmpty() },
            "permit_date" to date(item, "pmsDay"), "construction_date" to date(item, "stcnsDay"), "approval_date" to date(item, "useAprDay"),
            "record_created_date" to date(item, "crtnDay"), "energy_grade" to item["engrGrade"].orEmpty(),
            "green_grade" to item["gnBldGrade"].orEmpty(), "green_score" to item["gnBldCert"].orEmpty(),
            "intelligent_grade" to item["itgBldGrade"].orEmpty(), "intelligent_score" to item["itgBldCert"].orEmpty(),
            "earthquake_design" to when (item["rserthqkDsgnApplyYn"]) { "1", "Y" -> "적용"; "0", "N" -> "미적용"; else -> null },
            "earthquake_capacity" to item["rserthqkAblty"].orEmpty(), "registry_type" to item["regstrGbCdNm"].orEmpty(),
            "registry_kind" to item["regstrKindCdNm"].orEmpty())
    }
    private fun building(item: Map<String, String>) = mapOf("id" to item["mgmBldrgstPk"].orEmpty(),
        "dong_name" to item["dongNm"].orEmpty(), "building_name" to item["bldNm"].orEmpty(),
        "auxiliary" to (item["mainAtchGbCd"] == "1" || item["mainAtchGbCdNm"] == "부속건축물"), "fields" to fields(item))

    private fun unit(address: ListingAddressValue, selected: Map<String, String>?, input: BuildingLookupInput): Map<String, Any?> {
        fun state(status: String, message: String) = mapOf("status" to status, "message" to message)
        if (input.unitNumber.isBlank()) return state("not_requested", "호수는 선택 입력입니다. 호실을 확인하면 전유면적을 조회할 수 있습니다.")
        if (input.propertyType == "land") return state("not_applicable", "토지의 면적은 토지대장 등 별도 자료로 확인해주세요.")
        if (selected == null) return state("ambiguous", "호실을 조회할 건물을 먼저 선택해주세요.")
        val dong = selected["dongNm"].orEmpty()
        val number = input.unitNumber.trim()
        val variants = listOf(if (number.endsWith("호")) number else number + "호", number).distinct()
        var page: Page? = null
        for (variant in variants) {
            val result = read("getBrExposPubuseAreaInfo", address, mapOf("hoNm" to variant) + if (dong.isBlank()) emptyMap() else mapOf("dongNm" to dong))
            page = result
            if (result.items.isNotEmpty()) break
        }
        val result = requireNotNull(page)
        val matched = result.items.filter { reference(it["hoNm"].orEmpty(), "호") == reference(number, "호") &&
            reference(it["dongNm"].orEmpty(), "동") == reference(dong, "동") }
        if (!result.complete) return state("incomplete", "호실 조회 범위를 모두 확인하지 못해 전유면적을 적용할 수 없습니다.")
        if (matched.isEmpty()) return state("not_found", if (input.propertyType == "detached") "호별 전유부를 찾지 못했습니다. 다가구는 호(가구)별 면적대장을 별도로 확인해주세요." else "입력한 건물·호실의 전유부를 찾지 못했습니다. 면적은 직접 입력할 수 있습니다.")
        val ids = matched.map { it["mgmBldrgstPk"].orEmpty() }.distinct()
        if (ids.size != 1 || ids.single().isBlank()) return state("ambiguous", "동·호에 대응하는 대장이 여러 개이거나 식별되지 않아 면적을 확정하지 않았습니다.")
        val exclusive = matched.filter { it["exposPubuseGbCd"] == "1" }
        val components = exclusive.map { listOf(it["flrGbCd"], it["flrNo"], it["mainAtchGbCd"], it["mainPurpsCd"], it["etcPurps"], it["strctCd"]) }
        val areas = exclusive.map { decimal(it, "area", true) }
        val valid = areas.isNotEmpty() && areas.all { it != null } && components.distinct().size == components.size
        val sum = if (valid) areas.filterNotNull().fold(BigDecimal.ZERO, BigDecimal::add).takeIf { it <= BigDecimal("100000000") } else null
        val floors = exclusive.map(::floorName)
        return mapOf("status" to if (sum != null) "found" else "incomplete", "message" to if (sum != null) "해당 동·호의 건축물대장 전유면적입니다. 현재 광고의 동일성·소유권 확인은 별도입니다." else "전유면적 누락·중복 기록이 있어 자동 적용하지 않았습니다.",
            "register_id" to ids.single(), "dong_name" to dong, "unit_name" to matched.first()["hoNm"], "exclusive_area_sqm" to sum,
            "floor" to floors.takeIf { it.isNotEmpty() && it.all(String::isNotBlank) }?.distinct()?.singleOrNull(), "use" to exclusive.mapNotNull { it["mainPurpsCdNm"] }.distinct().joinToString(" · "),
            "common_areas" to matched.filter { it["exposPubuseGbCd"] == "2" }.map { mapOf("area_sqm" to decimal(it, "area", true),
                "floor" to it["flrNoNm"].orEmpty(), "use" to it["mainPurpsCdNm"].orEmpty()) }, "checked_at" to result.checkedAt)
    }

    fun lookup(input: BuildingLookupInput, owner: Long): Map<String, Any?> {
        if (input.buildingId.length > 100 || input.buildingDong.length > 30 || input.unitNumber.length > 30 || input.propertyType !in types)
            throw ApiFailure(422, "건물·동·호 조회 조건을 확인해주세요")
        val address = addresses.verify(input.addressToken, owner)
        val notes = mutableListOf("건축물대장 기재 정보이며 현장 상태·현재 호가·거래 가능 여부를 확인한 자료가 아닙니다.",
            "위반건축물 여부는 최신 대장으로 별도 확인해야 합니다. 건폐율·용적률은 대장 기재값이며 법적 최대 허용치가 아닙니다.")
        val output = linkedMapOf<String, Any?>("source" to "building_register", "checked_at" to Instant.now().toString(), "status" to "unavailable",
            "buildings" to emptyList<Any>(), "complex" to null, "selected_building" to null, "floors" to emptyList<Any>(),
            "unit" to mapOf("status" to "not_requested"), "zones" to emptyList<Any>(), "sanitation" to emptyList<Any>(), "notes" to notes)
        if (key.isBlank() || address.parcelMainNo.isBlank()) {
            notes.add(if (key.isBlank()) "건축물대장 조회 설정이 없습니다. 직접 입력은 계속 사용할 수 있습니다." else "이 주소 선택 정보에는 지번 식별값이 없습니다. 주소를 다시 검색해주세요.")
            return output
        }
        val failures = mutableListOf<String>()
        val initial = java.util.concurrent.Executors.newVirtualThreadPerTaskExecutor().use { pool ->
            listOf("getBrTitleInfo", "getBrRecapTitleInfo", "getBrJijiguInfo", "getBrWclfInfo").map { endpoint ->
                endpoint to pool.submit<Page?> { runCatching { read(endpoint, address) }.getOrNull() }
            }.associate { (endpoint, task) -> endpoint to task.get() }
        }
        initial.filterValues { it == null }.keys.forEach { failures.add(it) }
        val observations = initial.mapValues { it.value?.checkedAt }.toMutableMap()
        val titles = initial["getBrTitleInfo"]
        val records = titles?.items.orEmpty().filter { !it["mgmBldrgstPk"].isNullOrBlank() }.distinctBy { it["mgmBldrgstPk"] }
        val main = records.filter { it["mainAtchGbCd"] != "1" && it["mainAtchGbCdNm"] != "부속건축물" }
        val selected = when {
            input.buildingId.isNotBlank() -> records.singleOrNull { it["mgmBldrgstPk"] == input.buildingId }
                ?: throw ApiFailure(422, "선택한 주소에 해당 건물이 없습니다. 건물을 다시 선택해주세요.")
            titles?.complete != true -> null
            input.buildingDong.isNotBlank() -> records.filter { reference(it["dongNm"].orEmpty(), "동") == reference(input.buildingDong, "동") }.singleOrNull()
            main.size == 1 -> main.single()
            else -> null
        }
        if (input.buildingId.isNotBlank() && input.buildingDong.isNotBlank() && selected != null &&
            reference(selected["dongNm"].orEmpty(), "동") != reference(input.buildingDong, "동")) throw ApiFailure(422, "선택한 건물과 입력한 동이 다릅니다.")
        output["buildings"] = records.map(::building)
        output["complex"] = initial["getBrRecapTitleInfo"]?.items?.singleOrNull()?.let { mapOf("fields" to fields(it)) }
        output["selected_building"] = selected?.let(::building)
        output["zones"] = initial["getBrJijiguInfo"]?.items.orEmpty().map { mapOf("category" to it["jijiguGbCdNm"].orEmpty(), "name" to it["jijiguCdNm"].orEmpty(), "other" to it["etcJijigu"].orEmpty()) }
        output["sanitation"] = initial["getBrWclfInfo"]?.items.orEmpty().map { mapOf("type" to it["formCdNm"].orEmpty().ifBlank { it["formNm"].orEmpty() },
            "capacity_people" to decimal(it, "capaPsper", true), "capacity_m3" to decimal(it, "capaLube", true)) }
        if (selected != null) {
            val details = java.util.concurrent.Executors.newVirtualThreadPerTaskExecutor().use { pool ->
                val floors = pool.submit<Page?> { runCatching { read("getBrFlrOulnInfo", address) }.getOrNull() }
                val unit = pool.submit<Map<String, Any?>> { runCatching { unit(address, selected, input) }.getOrElse {
                    mapOf("status" to "unavailable", "message" to "호실 조회에 연결하지 못했습니다. 면적은 직접 입력할 수 있습니다.") } }
                floors.get() to unit.get()
            }
            if (details.first == null) failures.add("getBrFlrOulnInfo")
            observations["getBrFlrOulnInfo"] = details.first?.checkedAt
            output["floors"] = details.first?.items.orEmpty().filter { it["mgmBldrgstPk"] == selected["mgmBldrgstPk"] }.map {
                mapOf("floor" to floorName(it), "use" to it["mainPurpsCdNm"].orEmpty(),
                    "other_use" to it["etcPurps"].orEmpty(), "structure" to it["strctCdNm"].orEmpty(), "area_sqm" to decimal(it, "area", true)) }
            output["unit"] = details.second
            if (details.first?.complete == false) notes.add("층별 정보는 조회 범위 제한으로 일부만 표시됩니다.")
        } else if (input.unitNumber.isNotBlank()) output["unit"] = mapOf("status" to "ambiguous", "message" to "호실을 조회할 건물을 선택하거나 건물 동을 확인해주세요.")
        if (failures.isNotEmpty()) notes.add("일부 건축물대장 항목의 조회에 실패했습니다. 미제공 항목을 없음 또는 정상으로 판단하지 않습니다.")
        if (initial.values.any { it?.complete == false }) notes.add("조회 범위 제한으로 일부 기록만 표시됩니다. 전체 정보로 판단하지 마세요.")
        output["status"] = when { titles == null -> "unavailable"; records.isEmpty() -> "not_found"; !titles.complete || failures.isNotEmpty() -> "partial"; selected == null -> "ambiguous"; else -> "found" }
        output["record_checked_at"] = observations
        if (records.isNotEmpty()) {
            // 주소 서명과 구분하고 현재 사용자·필지·입력 동호에 묶는다. 토큰은 저장 자료가 아니다.
            val evidence = output.filterKeys { it !in setOf("buildings", "building_token") }
            val body = encoded(json.writeValueAsBytes(mapOf("owner" to owner, "expires" to Instant.now().epochSecond + 3600,
                "parcel" to parcel(address), "input_dong" to input.buildingDong, "input_unit" to input.unitNumber, "evidence" to evidence)))
            output["building_token"] = body + "." + encoded(signature(body))
        }
        return output
    }

    fun verify(input: BuildingProofInput): JsonNode {
        try {
            require(input.token.length <= 150000 && input.userId > 0 && input.areaSqm.isFinite() && input.areaSqm > 0)
            val parts = input.token.split('.'); require(parts.size == 2)
            require(MessageDigest.isEqual(signature(parts[0]), Base64.getUrlDecoder().decode(parts[1])))
            val body = json.readTree(Base64.getUrlDecoder().decode(parts[0]))
            require(body.path("owner").isIntegralNumber && body.path("owner").asLong() == input.userId && body.path("expires").isIntegralNumber && body.path("expires").asLong() > Instant.now().epochSecond)
            val address = addresses.verify(input.addressToken, input.userId)
            require(body.path("parcel").asText() == parcel(address))
            require(reference(body.path("input_dong").asText(), "동") == reference(input.buildingDong, "동") && reference(body.path("input_unit").asText(), "호") == reference(input.unitNumber, "호"))
            val evidence = body.path("evidence").deepCopy<com.fasterxml.jackson.databind.node.ObjectNode>()
            val area = evidence.path("unit").path("exclusive_area_sqm")
            evidence.put("area_matches_input", input.areaBasis == "exclusive" && area.isNumber && area.decimalValue().compareTo(BigDecimal.valueOf(input.areaSqm)) == 0)
            return evidence
        } catch (_: IllegalArgumentException) { throw ApiFailure(422, "건축물대장 확인 정보가 만료되었거나 주소·동·호가 바뀌었습니다. 다시 조회해주세요.") }
        catch (_: com.fasterxml.jackson.core.JacksonException) { throw ApiFailure(422, "건축물대장 확인 정보 형식을 확인해주세요") }
    }
}
