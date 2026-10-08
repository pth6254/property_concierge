package kr.propertyconcierge.core.calculations

import com.fasterxml.jackson.databind.ObjectMapper
import java.math.BigDecimal
import java.math.RoundingMode

data class FundingRequest(
    val purchasePrice: Long, val caseId: Long? = null, val candidateId: Long? = null,
    val cashAvailable: Long? = null, val monthlyPaymentLimit: Long? = null,
    val loanRatio: BigDecimal = decimal("0.5"), val annualInterestRate: BigDecimal = decimal("4.0"),
    val loanYears: Int = 30, val repaymentType: String = "equal_payment", val holdingYears: Int = 3,
    val expectedAnnualGrowthRate: BigDecimal = BigDecimal.ZERO, val rentDeposit: Long? = null, val assumedDeposit: Long? = null, val rentFee: Long? = null,
    val monthlyManagementFee: Long? = null, val propertyType: String = "아파트", val ownedHomes: Int = 1,
    val officialPrice: Long? = null, val residenceYears: Int? = null, val vacancyRate: BigDecimal = decimal("5.0"),
    val adjustedArea: Boolean = false, val annualIncome: Long? = null, val existingLoanAnnualPayment: Long = 0,
) {
    fun input(): SimulationInput {
        range(loanRatio, "0", "0.9")
        monthlyPaymentLimit?.let { money(it) }
        return SimulationInput(purchasePrice = purchasePrice, cashAvailable = cashAvailable,
            // 대출 비율에서 원 단위를 만들 때만 버림을 유지한다. 이후 금액은 HALF_EVEN 반올림이다.
            loanAmount = (bd(purchasePrice) * loanRatio).setScale(0, RoundingMode.DOWN).longValueExact(),
            annualInterestRate = annualInterestRate, loanYears = loanYears, repaymentType = repaymentType,
            holdingYears = holdingYears, expectedAnnualGrowthRate = expectedAnnualGrowthRate,
            rentDeposit = rentDeposit, assumedDeposit = assumedDeposit, rentFee = rentFee, monthlyManagementFee = monthlyManagementFee,
            propertyType = propertyType, ownedHomes = ownedHomes, officialPrice = officialPrice, residenceYears = residenceYears,
            vacancyRate = vacancyRate, adjustedArea = adjustedArea, annualIncome = annualIncome,
            existingLoanAnnualPayment = existingLoanAnnualPayment).also { it.check() }
    }
    fun summary(result: SimulationResult, json: ObjectMapper): Map<String, Any?> {
        val inputs = json.valueToTree<com.fasterxml.jackson.databind.node.ObjectNode>(this)
        inputs.remove(listOf("case_id", "candidate_id"))
        return mapOf("funding_version" to 1, "home_count_basis" to "after_purchase", "purchase_price" to purchasePrice,
            "calculator_engine" to result.calculatorEngine, "calculation_version" to result.calculationVersion,
            "tax_rules_as_of" to result.taxRulesAsOf, "loan_amount" to result.loanAmount, "annual_interest_rate" to annualInterestRate,
            "monthly_payment" to result.loan.monthlyPayment, "required_cash" to result.requiredCash,
            "acquisition_cost" to result.acquisitionCost.total,
            // 승계한 보증금은 임대 종료 때 현금으로 돌려줄 의무다. 필요 현금 감소와 함께 보여준다.
            "assumed_deposit" to assumedDeposit, "deposit_return_obligation" to assumedDeposit, "cash_available" to cashAvailable,
            // 보증금은 반환 의무가 있으므로 잔금에 필요한 현금에서 자동 차감하지 않는다.
            "cash_shortfall" to cashAvailable?.let { (result.requiredCash - it).coerceAtLeast(0) },
            "monthly_payment_limit" to monthlyPaymentLimit, "monthly_payment_exceeded" to monthlyPaymentLimit?.let { result.loan.monthlyPayment > it },
            "dsr_ratio" to result.financeCheck.dsr, "finance_check" to result.financeCheck,
            "annual_equity_roi" to result.scenarioBase.annualEquityRoi, "inputs" to inputs)
    }
    fun needsReview(result: SimulationResult) = cashAvailable == null || result.requiredCash > cashAvailable ||
        (result.loanAmount > 0 && (monthlyPaymentLimit == null || result.loan.monthlyPayment > monthlyPaymentLimit ||
            result.financeCheck.dsr == null || result.financeCheck.ltvExceeded || result.financeCheck.dsrExceeded))
}

data class FundingSummaryInput(val request: FundingRequest, val calculated: SimulationResult)
