package kr.propertyconcierge.core.listings

import com.fasterxml.jackson.databind.PropertyNamingStrategies
import com.fasterxml.jackson.module.kotlin.jacksonObjectMapper
import com.fasterxml.jackson.module.kotlin.readValue
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import kr.propertyconcierge.core.CoreConfiguration
import kr.propertyconcierge.core.bridge.PythonClient
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.transaction.support.TransactionTemplate
import org.mockito.Mockito.*
import org.mockito.ArgumentCaptor

class ListingContractTest {
    @Test
    fun `매물 페이지와 관측 이력을 건별 추가 조회 없이 읽는다`() {
        val jdbc = mock(JdbcTemplate::class.java)
        val service = ListingService(jdbc, CoreConfiguration().objectMapper(), mock(PythonClient::class.java), mock(TransactionTemplate::class.java))
        `when`(jdbc.queryForObject(anyString(), eq(Long::class.java), eq(1L))).thenReturn(0L)
        `when`(jdbc.queryForList(anyString(), eq(1L), eq(5), eq(0))).thenReturn(emptyList())
        service.search(1, ListingFilters(null, null, null, null, null, null, false, 1, 5))
        val query = ArgumentCaptor.forClass(String::class.java)
        verify(jdbc).queryForObject(anyString(), eq(Long::class.java), eq(1L))
        verify(jdbc).queryForList(query.capture(), eq(1L), eq(5), eq(0))
        val sql = query.value
        org.junit.jupiter.api.Assertions.assertTrue(sql.indexOf("LIMIT ? OFFSET ?") < sql.indexOf("LEFT JOIN LATERAL"))
        org.junit.jupiter.api.Assertions.assertTrue(sql.contains("listing_observations"))
        verifyNoMoreInteractions(jdbc)
    }
    @Test
    fun `기존 snake case 수입 요청을 Kotlin 입력으로 읽는다`() {
        val json = jacksonObjectMapper().setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE)
        val body = json.readValue<ImportInput>("""{"source_name":"검증","csv_text":"header\nvalue","commit":false}""")
        assertEquals("검증", body.sourceName)
        assertEquals("header\nvalue", body.csvText)
    }
}
