package kr.propertyconcierge.core.addresses

import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.CoreConfiguration
import kr.propertyconcierge.core.integrations.ExternalJsonClient
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.mockito.Mockito.*
import org.springframework.data.redis.core.StringRedisTemplate
import org.springframework.mock.env.MockEnvironment
import java.math.BigDecimal
import java.net.URI
import java.net.URLDecoder
import java.nio.charset.StandardCharsets.UTF_8

class BuildingRegisterTest {
    private val json = CoreConfiguration().objectMapper()
    private val env = MockEnvironment().withProperty("JWT_SECRET_KEY", "building-test-secret")
        .withProperty("MOLIT_API_KEY", "not-a-production-key").withProperty("BUILDING_REGISTER_API_ROOT", "http://provider/register")
    private val http = mock(ExternalJsonClient::class.java)
    private val addresses = ListingAddressService(http, json, env)
    private val service = BuildingRegisterService(addresses, http, json, mock(StringRedisTemplate::class.java), env)
    private val address = ListingAddressValue("서울 강남구 테헤란로 123", "서울 강남구 역삼동 123", "1168010100", 37.5, 127.04,
        "검증 건물", "kakao_address", "found", checkedAt="2026-10-02T00:00:00Z", identityLevel="building", parcelMainNo="123")
    private fun record(vararg values: Pair<String, String>) = mapOf("sigunguCd" to "11680", "bjdongCd" to "10100", "bun" to "0123", "ji" to "0000", "platGbCd" to "0") + values
    private fun title(id: String = "building-a", dong: String = "A동", auxiliary: Boolean = false) = record("mgmBldrgstPk" to id,
        "dongNm" to dong, "bldNm" to "검증 건물", "mainAtchGbCd" to if (auxiliary) "1" else "0", "mainPurpsCdNm" to "아파트",
        "totArea" to "5000", "useAprDay" to "19991125", "crtnDay" to "20261002")
    private fun unit(dong: String = "A동", ho: String = "501호", area: String = "84.9", kind: String = "1") = record(
        "mgmBldrgstPk" to "unit-$dong-$ho", "dongNm" to dong, "hoNm" to ho, "area" to area, "exposPubuseGbCd" to kind,
        "flrNo" to "5", "flrNoNm" to "5층", "mainAtchGbCd" to "0", "mainPurpsCd" to "02001", "mainPurpsCdNm" to "아파트", "strctCd" to "21")
    private fun provider(records: Map<String, List<Map<String, String>>>, total: Map<String, Int> = emptyMap()) {
        `when`(http.form(anyMap())).thenCallRealMethod()
        `when`(http.encoded(anyString())).thenCallRealMethod()
        `when`(http.text(eq("GET") ?: "GET", anyString(), anyMap(), isNull())).thenAnswer { invocation ->
            val url = invocation.getArgument<String>(1)
            val endpoint = url.substringBefore('?').substringAfterLast('/')
            val items = records[endpoint].orEmpty()
            "<response><resultCode>00</resultCode><totalCount>${total[endpoint] ?: items.size}</totalCount><items>" +
                items.joinToString("") { item -> "<item>" + item.entries.joinToString("") { "<${it.key}>${it.value}</${it.key}>" } + "</item>" } + "</items></response>"
        }
    }
    private fun lookup(dong: String = "", ho: String = "", building: String = "", type: String = "apartment") =
        service.lookup(BuildingLookupInput(addresses.sign(address, 1), building, dong, ho, type), 1)
    @Test fun `원문 및 인코딩 인증키의 플러스 문자를 실제 요청에서 보존한다`() {
        for (key in listOf("test+key/=", "test%2Bkey%2F%3D")) {
            env.withProperty("MOLIT_API_KEY", key)
            val realClient = ExternalJsonClient(json)
            doAnswer { realClient.form(it.getArgument(0)) }.`when`(http).form(anyMap())
            doAnswer {
                val query = URI(it.getArgument<String>(1)).rawQuery.split('&').associate { pair ->
                    val parts = pair.split('=', limit=2); parts[0] to URLDecoder.decode(parts[1], UTF_8)
                }
                assertEquals("test+key/=", query["serviceKey"])
                "<response><resultCode>00</resultCode><totalCount>0</totalCount><items/></response>"
            }.`when`(http).text(eq("GET") ?: "GET", anyString(), anyMap(), isNull())
            val configured = BuildingRegisterService(addresses, http, json, mock(StringRedisTemplate::class.java), env)
            assertEquals("not_found", configured.lookup(BuildingLookupInput(addresses.sign(address, 1)), 1)["status"])
        }
    }
    @Test fun `첫 부속건물을 선택하지 않고 주건축물의 범위를 보존한다`() {
        provider(mapOf("getBrTitleInfo" to listOf(title("guard", "경비실", true), title()),
            "getBrRecapTitleInfo" to listOf(record("mgmBldrgstPk" to "complex", "totArea" to "20000"))))
        val result = json.valueToTree<com.fasterxml.jackson.databind.JsonNode>(lookup())
        assertEquals("building-a", result.path("selected_building").path("id").asText())
        assertEquals(5000, result.path("selected_building").path("fields").path("total_area_sqm").asInt())
        assertEquals(20000, result.path("complex").path("fields").path("total_area_sqm").asInt())
        assertEquals("not_requested", result.path("unit").path("status").asText())
    }
    @Test fun `여러 동은 임의 선택하지 않고 잘못된 동에도 첫 결과를 쓰지 않는다`() {
        provider(mapOf("getBrTitleInfo" to listOf(title(), title("building-b", "B동"))))
        assertEquals("ambiguous", lookup()["status"])
        assertNull(lookup("C동")["selected_building"])
        assertThrows(ApiFailure::class.java) { lookup(building="unknown") }
    }
    @Test fun `공용면적과 다른 동호를 제외하고 실제 area 필드의 전유면적을 사용한다`() {
        provider(mapOf("getBrTitleInfo" to listOf(title()), "getBrExposPubuseAreaInfo" to listOf(unit("B동"), unit(), unit(area="35.2", kind="2"))))
        val result = json.valueToTree<com.fasterxml.jackson.databind.JsonNode>(lookup("A", "501"))
        assertEquals("found", result.path("unit").path("status").asText())
        assertEquals(BigDecimal("84.9"), result.path("unit").path("exclusive_area_sqm").decimalValue())
        assertEquals(1, result.path("unit").path("common_areas").size())
        assertEquals("not_found", json.valueToTree<com.fasterxml.jackson.databind.JsonNode>(lookup("A", "999")).path("unit").path("status").asText())
    }
    @Test fun `동명칭 없는 건물은 호수만으로 조회한다`() {
        provider(mapOf("getBrTitleInfo" to listOf(title(dong="")), "getBrExposPubuseAreaInfo" to listOf(unit(dong=""))))
        val result = json.valueToTree<com.fasterxml.jackson.databind.JsonNode>(lookup(ho="501"))
        assertEquals("found", result.path("unit").path("status").asText())
    }
    @Test fun `층 미제공이면 호수에서 층을 추정하지 않는다`() {
        provider(mapOf("getBrTitleInfo" to listOf(title()), "getBrExposPubuseAreaInfo" to listOf(unit() + mapOf("flrNo" to "", "flrNoNm" to ""))))
        val result = json.valueToTree<com.fasterxml.jackson.databind.JsonNode>(lookup("A", "501"))
        assertEquals("found", result.path("unit").path("status").asText())
        assertTrue(result.path("unit").path("floor").isNull)
    }
    @Test fun `전유면적 누락과 중복 및 불완전 페이지를 확정 면적으로 바꾸지 않는다`() {
        for (items in listOf(listOf(unit(area="0")), listOf(unit(), unit()))) {
            provider(mapOf("getBrTitleInfo" to listOf(title()), "getBrExposPubuseAreaInfo" to items))
            val result = json.valueToTree<com.fasterxml.jackson.databind.JsonNode>(lookup("A", "501"))
            assertEquals("incomplete", result.path("unit").path("status").asText())
            assertTrue(result.path("unit").path("exclusive_area_sqm").isNull)
        }
        provider(mapOf("getBrTitleInfo" to listOf(title()), "getBrExposPubuseAreaInfo" to listOf(unit())), mapOf("getBrExposPubuseAreaInfo" to 600))
        assertEquals("incomplete", json.valueToTree<com.fasterxml.jackson.databind.JsonNode>(lookup("A", "501")).path("unit").path("status").asText())
    }
    @Test fun `사용승인일이 없으면 자료 생성일을 준공일로 대체하지 않는다`() {
        provider(mapOf("getBrTitleInfo" to listOf(title() + ("useAprDay" to ""))))
        val result = json.valueToTree<com.fasterxml.jackson.databind.JsonNode>(lookup())
        assertTrue(result.path("selected_building").path("fields").path("approval_date").isNull)
        assertEquals("2026-10-02", result.path("selected_building").path("fields").path("record_created_date").asText())
    }
    @Test fun `확인 서명은 사용자 필지 동호에 묶이고 면적 차이는 그대로 남긴다`() {
        provider(mapOf("getBrTitleInfo" to listOf(title()), "getBrExposPubuseAreaInfo" to listOf(unit())))
        val token = lookup("A", "501")["building_token"] as String
        val input = BuildingProofInput(token, 1, addresses.sign(address, 1), "A동", "501호", 84.9, "exclusive")
        assertTrue(service.verify(input).path("area_matches_input").asBoolean())
        assertFalse(service.verify(input.copy(areaSqm=80.0)).path("area_matches_input").asBoolean())
        assertThrows(ApiFailure::class.java) { service.verify(input.copy(unitNumber="502")) }
        assertThrows(ApiFailure::class.java) { service.verify(input.copy(userId=2, addressToken=addresses.sign(address, 2))) }
        assertThrows(ApiFailure::class.java) { service.verify(input.copy(addressToken=addresses.sign(address.copy(parcelMainNo="124"), 1))) }
        assertThrows(ApiFailure::class.java) { service.verify(input.copy(token=token + "x")) }
    }
    @Test fun `조회 실패는 미확인으로 남기고 공급자 오류 문자열을 공개하지 않는다`() {
        `when`(http.form(anyMap())).thenReturn("key=test")
        `when`(http.text(eq("GET") ?: "GET", anyString(), anyMap(), isNull())).thenThrow(ApiFailure(502, "secret-value"))
        val result = lookup()
        assertEquals("unavailable", result["status"])
        assertFalse(json.writeValueAsString(result).contains("secret-value"))
    }
}
