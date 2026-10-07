package kr.propertyconcierge.core.calculations

import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.CoreConfiguration
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import java.math.BigDecimal

class IncomeValuationCalculatorTest {
    private val calculator = IncomeValuationCalculator()
    private val json = CoreConfiguration().objectMapper()
    private val input = IncomeValuationInput(10_000_000, 1_000_000, 2_000_000, BigDecimal("4"), BigDecimal("6"),
        2_000_000_000, "whole_building", "2026-01-01")
    @Test fun `현재 월세의 연환산과 NOI 환원율 조합의 극값을 계산한다`() {
        val out = json.valueToTree<com.fasterxml.jackson.databind.JsonNode>(calculator.calculate(input))
        assertEquals(120_000_000, out.path("annual_rent_won").asLong())
        assertEquals(96_000_000, out.path("annual_noi_min_won").asLong())
        assertEquals(108_000_000, out.path("annual_noi_max_won").asLong())
        assertEquals(1_600_000_000, out.path("low_price_won").asLong())
        assertEquals(2_700_000_000, out.path("high_price_won").asLong())
        assertEquals(6.0, out.path("gross_yield_pct").asDouble())
        assertEquals(4.8, out.path("net_yield_min_pct").asDouble())
        assertEquals(5.4, out.path("net_yield_max_pct").asDouble())
        assertEquals(3, out.path("scenarios").size())
        assertEquals("user_assumption", out.path("cap_rate_source").asText())
    }
    @Test fun `비용 미확인과 비용 영원은 서로 다른 결과다`() {
        val unknown = calculator.calculate(input.copy(monthlyOperatingCostMinWon=null, monthlyOperatingCostMaxWon=null))
        assertEquals("withheld", unknown["result_kind"]); assertNull(unknown["low_price_won"])
        assertNull(unknown["annual_noi_min_won"]); assertNotNull(unknown["gross_yield_pct"])
        val zero = calculator.calculate(input.copy(monthlyOperatingCostMinWon=0, monthlyOperatingCostMaxWon=0))
        assertEquals("conditional_scenario", zero["result_kind"])
        assertEquals(120_000_000L, zero["annual_noi_min_won"])
    }
    @Test fun `공실 영원 및 적자에서 양수 가격을 강제하지 않는다`() {
        for (value in listOf(input.copy(monthlyRentWon=0), input.copy(monthlyOperatingCostMaxWon=10_000_000))) {
            val out = calculator.calculate(value)
            assertEquals("withheld", out["result_kind"]); assertNull(out["low_price_won"]); assertNull(out["high_price_won"])
        }
    }
    @Test fun `호가 미입력은 수익률만 미산출이며 가격 시나리오는 유지한다`() {
        val out = calculator.calculate(input.copy(askingPriceWon=null))
        assertNull(out["gross_yield_pct"]); assertNull(out["net_yield_min_pct"]); assertNotNull(out["low_price_won"])
    }
    @Test fun `역전 범위 영환원율 부분비용 미래일 소수정밀도는 거절한다`() {
        for (value in listOf(input.copy(capRateMinPct=BigDecimal.ZERO), input.copy(capRateMaxPct=BigDecimal("3")),
            input.copy(monthlyOperatingCostMinWon=3_000_000), input.copy(monthlyOperatingCostMinWon=null),
            input.copy(asOfDate="2999-01-01"), input.copy(askingPriceWon=0), input.copy(valuationUnit="land"),
            input.copy(capRateMinPct=BigDecimal("0.12345")))) {
            assertThrows(ApiFailure::class.java) { calculator.calculate(value) }
        }
    }
    @Test fun `원 단위는 HALF EVEN으로 반올림하고 금액 범위를 자르지 않는다`() {
        val out = calculator.calculate(input.copy(monthlyRentWon=1, monthlyOperatingCostMinWon=0, monthlyOperatingCostMaxWon=0,
            capRateMinPct=BigDecimal("32"), capRateMaxPct=BigDecimal("32")))
        assertEquals(38L, out["low_price_won"])
        assertThrows(ArithmeticException::class.java) { calculator.calculate(input.copy(monthlyRentWon=1_000_000_000_000_000,
            monthlyOperatingCostMinWon=0, monthlyOperatingCostMaxWon=0, capRateMinPct=BigDecimal("0.1"))) }
    }
    @Test fun `외부 JSON 소수 금액과 필수값 null을 허용하지 않는다`() {
        for (patch in listOf("monthly_rent_won" to json.nullNode(), "monthly_rent_won" to json.valueToTree(BigDecimal("0.1")))) {
            val body = json.valueToTree<com.fasterxml.jackson.databind.node.ObjectNode>(input).set<com.fasterxml.jackson.databind.node.ObjectNode>(patch.first, patch.second)
            assertThrows(com.fasterxml.jackson.core.JacksonException::class.java) { json.treeToValue(body, IncomeValuationInput::class.java) }
        }
    }
}
