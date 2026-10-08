package kr.propertyconcierge.core.calculations

import kr.propertyconcierge.core.ApiFailure
import java.math.BigDecimal

const val MONEY_LIMIT = 1_000_000_000_000_000L

// 미확인 소득·공시가격은 null로 보존한다. 0으로 바꾸면 미검증 DSR을 통과로 오인할 수 있다.
data class SimulationInput(
    val purchasePrice: Long,
    val cashAvailable: Long? = null,
    val loanAmount: Long = 0,
    val annualInterestRate: BigDecimal = BigDecimal("4.0"),
    val loanYears: Int = 30,
    val repaymentType: String = "equal_payment",
    val holdingYears: Int = 3,
    val expectedAnnualGrowthRate: BigDecimal = BigDecimal.ZERO,
    val rentDeposit: Long? = null,
    val rentFee: Long? = null,
    // 기존 임차인의 보증금을 승계해 잔금에서 빼고 지급하는 금액. 새로 받을 임대 보증금(rentDeposit)과 다르다.
    val assumedDeposit: Long? = null,
    val monthlyManagementFee: Long? = null,
    val propertyType: String? = "아파트",
    val ownedHomes: Int = 1,
    val officialPrice: Long? = null,
    val residenceYears: Int? = null,
    val vacancyRate: BigDecimal = BigDecimal("5.0"),
    val adjustedArea: Boolean = false,
    val annualIncome: Long? = null,
    val existingLoanAnnualPayment: Long = 0,
    val scenarioSpread: BigDecimal = BigDecimal("5.0"),
    val jeonseOpportunityRate: BigDecimal = BigDecimal("3.5"),
) {
    fun check() {
        money(purchasePrice, positive = true)
        listOf(cashAvailable, loanAmount, rentDeposit, assumedDeposit, rentFee, monthlyManagementFee, officialPrice,
            annualIncome, existingLoanAnnualPayment).filterNotNull().forEach { money(it) }
        requireInput(loanAmount < purchasePrice)
        requireInput((rentDeposit ?: 0) < purchasePrice)
        // 승계 보증금과 대출을 합친 금액이 매매가 이상이면 잔금에 낼 현금이 음수가 된다.
        requireInput(loanAmount + (assumedDeposit ?: 0) < purchasePrice)
        requireInput((assumedDeposit ?: 0) == 0L || (rentDeposit ?: 0) == 0L)
        requireInput((rentDeposit ?: 0) == 0L || (rentFee ?: 0) == 0L)
        requireInput(loanYears in 1..50 && holdingYears in 1..50 && ownedHomes in 1..100)
        requireInput(residenceYears == null || residenceYears in 0..100)
        requireInput(repaymentType in setOf("equal_payment", "equal_principal", "interest_only"))
        range(annualInterestRate, "0", "30"); range(expectedAnnualGrowthRate, "-20", "50")
        range(vacancyRate, "0", "50"); range(scenarioSpread, "1", "20"); range(jeonseOpportunityRate, "0", "20")
    }
}

internal fun requireInput(valid: Boolean) { if (!valid) throw ApiFailure(422, "계산 입력의 범위와 조건을 확인해주세요") }
internal fun money(value: Long, positive: Boolean = false) = requireInput(value in (if (positive) 1L else 0L)..MONEY_LIMIT)
internal fun range(value: BigDecimal, low: String, high: String) = requireInput(
    value.scale() in -20..20 && value.precision() <= 40 && value >= BigDecimal(low) && value <= BigDecimal(high))

data class AcquisitionCost(val acquisitionTax: Long, val brokerageFee: Long, val otherCost: Long, val total: Long)
data class LoanSummary(val monthlyPayment: Long, val totalRepayment: Long, val totalInterest: Long)
data class CashFlowSummary(val monthlyRentalIncome: Long, val monthlyLoanPayment: Long, val monthlyManagementFee: Long, val monthlyNet: Long)
data class ScenarioResult(
    val annualGrowthRate: BigDecimal, val expectedSalePrice: Long, val capitalGain: Long,
    val totalRentalIncome: Long, val netProfit: Long, val equityRoi: Double, val annualEquityRoi: Double,
    val rentalYield: Double, val preTaxProfit: Long, val capitalGainsTax: Long, val holdingTaxTotal: Long,
    val saleBrokerageFee: Long, val cgtNote: String, val infiniteLeverage: Boolean,
)
data class FinanceCheck(
    val ltv: BigDecimal, val ltvLimit: BigDecimal, val ltvExceeded: Boolean, val ltvMaxLoan: Long,
    val dsr: BigDecimal? = null, val dsrLimit: BigDecimal = BigDecimal("0.40"), val dsrExceeded: Boolean = false,
    val stressRate: BigDecimal? = null, val dsrAnnualPayment: Long? = null, val dsrMaxLoan: Long? = null,
)
data class RateSensitivityCell(val growthRate: BigDecimal, val interestRate: BigDecimal, val annualEquityRoi: Double, val netProfit: Long)
data class SimulationResult(
    val purchasePrice: Long, val loanAmount: Long, val ownedHomes: Int, val homeCountBasis: String = "after_purchase",
    val equity: Long, val requiredCash: Long, val acquisitionCost: AcquisitionCost, val loan: LoanSummary,
    val cashFlow: CashFlowSummary, val scenarioBase: ScenarioResult, val scenarioBull: ScenarioResult, val scenarioBear: ScenarioResult,
    val taxRulesAsOf: String = TaxRules.AS_OF, val officialPriceUsed: Long, val officialPriceEstimated: Boolean,
    val financeCheck: FinanceCheck, val breakevenGrowthRate: BigDecimal?, val rateSensitivity: List<RateSensitivityCell>,
    val calculatorEngine: String = "kotlin-spring", val calculationVersion: String = "finance-v1",
    val roundingPolicy: String = "half_even_won",
)
