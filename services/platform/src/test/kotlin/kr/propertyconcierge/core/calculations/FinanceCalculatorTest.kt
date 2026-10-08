package kr.propertyconcierge.core.calculations

import com.fasterxml.jackson.core.JacksonException
import com.fasterxml.jackson.module.kotlin.readValue
import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.CoreConfiguration
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class FinanceCalculatorTest {
    private val engine = FinanceCalculator()
    private val json = CoreConfiguration().objectMapper()
    @Test fun `6억 첫 주택의 취득비용과 필요 현금을 수기로 대조한다`() {
        val result = engine.calculate(SimulationInput(600_000_000, loanAmount = 300_000_000))
        assertEquals(AcquisitionCost(6_600_000, 2_400_000, 600_000, 9_600_000), result.acquisitionCost)
        assertEquals(309_600_000L, result.requiredCash)
        assertEquals(1_432_246L, result.loan.monthlyPayment)
        assertEquals("kotlin-spring", result.calculatorEngine)
    }
    @Test fun `주택 수와 상업용 세율을 서로 구분한다`() {
        assertEquals(48_000_000L, engine.acquisition(600_000_000, "아파트", 2).acquisitionTax)
        assertEquals(72_000_000L, engine.acquisition(600_000_000, "아파트", 3).acquisitionTax)
        assertEquals(26_400_000L, engine.acquisition(600_000_000, "상가", 3).acquisitionTax)
    }
    @Test fun `상환 방식별 첫 달과 무이자 원금 잔액을 검증한다`() {
        assertEquals(1_833_333L, engine.monthly(300_000_000, decimal("4"), 30, "equal_principal"))
        assertEquals(1_000_000L, engine.monthly(300_000_000, decimal("4"), 30, "interest_only"))
        val zero = engine.loan(1, java.math.BigDecimal.ZERO, 30, "equal_payment")
        assertEquals(0L, zero.totalInterest); assertEquals(1L, zero.totalRepayment)
        assertEquals(12_000_000L, engine.interest(300_000_000, decimal("4"), 30, 1, "interest_only"))
    }
    @Test fun `0원 소득은 미검증이고 초과 판정은 반올림 전에 한다`() {
        val input = SimulationInput(600_000_000, loanAmount = 300_000_001, adjustedArea = true, annualIncome = 0)
        val check = engine.finance(input)
        assertTrue(check.ltvExceeded); assertNull(check.dsr)
        assertEquals(decimal("0.5000"), check.ltv)
    }
    @Test fun `전세 보증금과 현금 부족을 구분하고 무자본 수익률을 차단한다`() {
        val input = FundingRequest(600_000_000, loanRatio = decimal("0.9"), rentDeposit = 590_000_000, cashAvailable = 0)
        val result = engine.calculate(input.input())
        assertTrue(result.equity < 0 && result.scenarioBase.infiniteLeverage)
        assertEquals(0.0, result.scenarioBase.equityRoi)
        assertEquals(result.requiredCash, input.summary(result, json)["cash_shortfall"])
    }
    @Test fun `승계 보증금은 필요 현금에서 빼되 반환 의무를 기록하고 잘못된 조합을 거부한다`() {
        val plain = FundingRequest(600_000_000, loanRatio = decimal("0.5"), cashAvailable = 100_000_000)
        val assumed = plain.copy(assumedDeposit = 200_000_000)
        val base = engine.calculate(plain.input()); val result = engine.calculate(assumed.input())
        assertEquals(base.requiredCash - 200_000_000, result.requiredCash)
        assertEquals(base.acquisitionCost, result.acquisitionCost)
        val summary = assumed.summary(result, json)
        assertEquals(200_000_000L, summary["deposit_return_obligation"])
        assertEquals(null, plain.summary(base, json)["assumed_deposit"])
        assertThrows(ApiFailure::class.java) { engine.calculate(SimulationInput(600_000_000, loanAmount = 300_000_000, assumedDeposit = 300_000_000)) }
        assertThrows(ApiFailure::class.java) { engine.calculate(SimulationInput(600_000_000, assumedDeposit = 100_000_000, rentDeposit = 100_000_000)) }
        // 임차인이 거주 중인 집은 매수인의 거주 기간으로 보지 않아 장기보유특별공제 거주분이 달라진다.
        val owner = engine.calculate(SimulationInput(600_000_000, holdingYears = 3, expectedAnnualGrowthRate = decimal("10")))
        val tenanted = engine.calculate(SimulationInput(600_000_000, holdingYears = 3, expectedAnnualGrowthRate = decimal("10"), assumedDeposit = 100_000_000))
        assertEquals(owner.scenarioBase.expectedSalePrice, tenanted.scenarioBase.expectedSalePrice)
    }
    @Test fun `금액은 소수와 null을 거부하고 미확인 소득을 보존한다`() {
        for (body in listOf("""{"purchase_price":null}""", """{"purchase_price":1.5}""", """{"purchase_price":600000000,"loan_amount":null}"""))
            assertThrows(JacksonException::class.java) { json.readValue<SimulationInput>(body) }
        assertNull(json.readValue<SimulationInput>("""{"purchase_price":600000000}""").annualIncome)
        assertThrows(ApiFailure::class.java) { engine.calculate(SimulationInput(600_000_000, loanAmount = 600_000_000)) }
        assertThrows(ApiFailure::class.java) { engine.calculate(SimulationInput(600_000_000, rentDeposit = 1, rentFee = 1)) }
        assertEquals(100L, json.readValue<GiftInput>("""{"gift_value":500000000,"prior_gifts_10yr":100}""").priorGifts10yr)
    }
    @Test fun `손익분기 검색의 큰 경계가 유효한 50년 시나리오를 막지 않는다`() {
        val result = engine.calculate(SimulationInput(600_000_000, loanAmount = 300_000_000, holdingYears = 50))
        assertEquals(600_000_000L, result.scenarioBase.expectedSalePrice)
        assertNotNull(result.breakevenGrowthRate)
    }
    @Test fun `원 단위 동률 반올림과 대출 비율 버림은 명시한 규칙을 따른다`() {
        assertEquals(2L, decimal("2.5").won()); assertEquals(4L, decimal("3.5").won())
        assertEquals(-2L, decimal("-2.5").won())
        assertEquals(58L, FundingRequest(100, loanRatio = decimal("0.58")).input().loanAmount)
        assertThrows(ArithmeticException::class.java) { decimal("9223372036854775808").won() }
    }
    @Test fun `세금의 공제와 누진 세율을 고정 수기 사례로 검증한다`() {
        assertEquals(77_600_000L, TaxRules.gift(500_000_000).tax)
        assertEquals(232_800_000L, TaxRules.inheritance(2_000_000_000).tax)
        assertEquals(787_200L, TaxRules.holding(600_000_000).total)
        // 과표 25,500,000 × 15% − 1,260,000 = 2,565,000, 지방세 256,500을 더한다.
        assertEquals(2_821_500L, TaxRules.capitalGains(800_000_000, 1_500_000_000, 10, residence = 10).tax)
        assertTrue(TaxRules.capitalGains(800_000_000, 1_100_000_000, 2).exempt)
    }
}
