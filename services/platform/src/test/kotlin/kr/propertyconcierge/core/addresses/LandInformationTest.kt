package kr.propertyconcierge.core.addresses

import com.fasterxml.jackson.databind.JsonNode
import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.CoreConfiguration
import kr.propertyconcierge.core.integrations.ExternalJsonClient
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.mockito.Mockito.*
import org.springframework.mock.env.MockEnvironment
import java.net.URI
import java.net.URLDecoder
import java.nio.charset.StandardCharsets.UTF_8

class LandInformationTest {
    private val json = CoreConfiguration().objectMapper()
    private val env = MockEnvironment().withProperty("VWORLD_API_KEY", "test+key").withProperty("VWORLD_NED_ROOT", "https://provider")
    private val http = mock(ExternalJsonClient::class.java)
    private val addresses = mock(ListingAddressService::class.java)
    private val pnu = "1114010300100310000"
    private val address = ListingAddressValue("서울 중구 세종대로 110", "서울 중구 태평로1가 31", "1114010300", 37.56, 126.97,
        nameSource="unknown", nameStatus="unknown", checkedAt="2026-01-01T00:00:00Z", identityLevel="parcel", parcelMainNo="31")
    private val rows = mutableMapOf(
        "ladfrlList" to listOf(mapOf("pnu" to pnu, "lndpclAr" to "100.5", "lndcgrCodeNm" to "대", "lastUpdtDt" to "2026-01-01")),
        "getLandCharacteristics" to listOf(mapOf("pnu" to pnu, "stdrYear" to "2026", "stdrMt" to "01", "lndpclAr" to "100", "ladUseSittnNm" to "상업용", "tpgrphHgCodeNm" to "평지", "tpgrphFrmCodeNm" to "정방형", "roadSideCodeNm" to "소로한면", "prposArea1Nm" to "일반상업지역", "prposArea2Nm" to "지정되지않음")),
        "getIndvdLandPriceAttr" to listOf(mapOf("pnu" to pnu, "stdrYear" to "2026", "stdrMt" to "01", "pblntfPclnd" to "12345")),
        "getLandUseAttr" to listOf(mapOf("pnu" to pnu, "prposAreaDstrcCodeNm" to "일반상업지역", "cnflcAtNm" to "포함"))
    )
    private val wrappers = mapOf("ladfrlList" to "ladfrlVOList", "getLandCharacteristics" to "landCharacteristicss", "getIndvdLandPriceAttr" to "indvdLandPrices", "getLandUseAttr" to "landUses")
    private var errorCode = ""
    private var countExtra = 0
    init {
        `when`(addresses.parcel(anyString())).thenReturn(address)
        `when`(http.form(anyMap())).thenCallRealMethod(); `when`(http.encoded(anyString())).thenCallRealMethod()
        `when`(http.get(anyString(), anyMap())).thenAnswer { invocation ->
            val uri = URI(invocation.getArgument<String>(0))
            val query = uri.rawQuery.split('&').associate { pair -> val parts = pair.split('=', limit=2); parts[0] to URLDecoder.decode(parts[1], UTF_8) }
            assertEquals("test+key", query["key"]); assertEquals(pnu, query["pnu"])
            val endpoint = uri.path.substringAfterLast('/'); val values = rows[endpoint].orEmpty()
            json.valueToTree<JsonNode>(mapOf(wrappers.getValue(endpoint) to mapOf("resultCode" to errorCode, "totalCount" to values.size + countExtra,
                (if (endpoint == "ladfrlList") "ladfrlVOList" else "field") to values)))
        }
    }
    private fun lookup() = json.valueToTree<JsonNode>(LandInformationService(addresses, http, env).lookup(LandLookupInput(address.jibunAddress, "2026-01-01")))
    @Test fun `필지 일치한 공공자료를 합치고 현재 면적과 공시년 면적을 구분한다`() {
        val out = lookup()
        assertEquals("found", out.path("status").asText()); assertEquals(pnu, out.path("pnu").asText())
        assertEquals(100.5, out.path("fields").path("land_area_sqm").asDouble())
        assertEquals(1_234_500, out.path("official_reference_total_won").asLong())
        assertEquals(4, out.path("sources").size()); assertFalse(out.toString().contains("test+key"))
    }
    @Test fun `미래 연도 제외 후 최신 공시기준을 고르고 기준연도 불일치 총액은 보류한다`() {
        rows["getIndvdLandPriceAttr"] = listOf(mapOf("pnu" to pnu, "stdrYear" to "2027", "stdrMt" to "01", "pblntfPclnd" to "99999"),
            mapOf("pnu" to pnu, "stdrYear" to "2025", "stdrMt" to "01", "pblntfPclnd" to "11111"))
        val out = lookup(); assertEquals("2025", out.path("official_price_year").asText()); assertTrue(out.path("official_reference_total_won").isNull)
    }
    @Test fun `다른 필지 응답과 누락 필드를 영원이나 안전으로 바꾸지 않는다`() {
        rows["getLandCharacteristics"] = rows.getValue("getLandCharacteristics").map { it + mapOf("pnu" to "1114010300100320000") }
        val out = lookup(); assertEquals("partial", out.path("status").asText()); assertTrue(out.path("fields").path("road_frontage").isNull)
        assertEquals("parcel_mismatch", out.path("sources")[1].path("status").asText())
    }
    @Test fun `만료 키와 불완전 페이지는 성공 상태를 반환하지 않는다`() {
        errorCode = "EXPIRE_KEY"; val expired = lookup()
        assertEquals("unavailable", expired.path("status").asText()); assertEquals("key_expired", expired.path("sources")[0].path("status").asText())
        errorCode = ""; countExtra = 1
        assertEquals("incomplete", lookup().path("sources")[0].path("status").asText())
    }
    @Test fun `같은 기준일에 충돌하는 공시가는 임의 선택하지 않는다`() {
        rows["getIndvdLandPriceAttr"] = rows.getValue("getIndvdLandPriceAttr") + rows.getValue("getIndvdLandPriceAttr").map { it + mapOf("pblntfPclnd" to "9999") }
        assertTrue(lookup().path("fields").path("official_price_won_per_sqm").isNull)
    }
    @Test fun `주소가 모호하면 외부 토지 조회를 진행하지 않는다`() {
        `when`(addresses.parcel(anyString())).thenThrow(ApiFailure(422, "정확한 주소 필요"))
        assertThrows(ApiFailure::class.java) { lookup() }; verify(http, never()).get(anyString(), anyMap())
    }
}
