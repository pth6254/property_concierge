package kr.propertyconcierge.core.store

import com.fasterxml.jackson.core.JacksonException
import com.fasterxml.jackson.module.kotlin.readValue
import kr.propertyconcierge.core.CoreConfiguration
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class CaseNullContractTest {
    private val json = CoreConfiguration().objectMapper()
    @Test fun `확인하지 않은 예산과 금융 조건은 null로 유지한다`() {
        val input = json.readValue<CaseCreateInput>("""{"title":"매수 검토","budget_max":null,"buyer_profile":{"loan_ratio":null}}""")
        assertNull(input.budgetMax); assertNull(input.buyerProfile.loanRatio)
        assertEquals(0, input.buyerProfile.emergencyReserve)
    }
    @Test fun `필수 값과 리스트 원소의 null을 거부한다`() {
        for (body in listOf("""{"title":null}""", """{"title":"검토","buyer_profile":{"emergency_reserve":null}}""",
            """{"title":"검토","target_regions":[null]}"""))
            assertThrows(JacksonException::class.java) { json.readValue<CaseCreateInput>(body) }
    }
    @Test fun `잘못된 필드와 소수 금액을 조용히 보정하지 않는다`() {
        for (body in listOf("""{"title":"검토","budget_max":1.5}""", """{"title":"검토","unsupported":1}"""))
            assertThrows(JacksonException::class.java) { json.readValue<CaseCreateInput>(body) }
    }
}
