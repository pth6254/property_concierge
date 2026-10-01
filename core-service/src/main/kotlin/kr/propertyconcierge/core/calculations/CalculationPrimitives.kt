package kr.propertyconcierge.core.calculations

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import org.springframework.stereotype.Service
import java.math.BigDecimal

data class PriceInput(val purchasePrice: Long, val propertyType: String? = null, val ownedHomes: Int = 1)
data class LoanInput(val loanAmount: Long, val annualInterestRate: BigDecimal, val loanYears: Int,
    val repaymentType: String = "equal_payment", val holdingYears: Int = 1) {
    fun check() {
        money(loanAmount); range(annualInterestRate, "0", "30")
        requireInput(loanYears in 1..50 && holdingYears in 0..100)
        requireInput(repaymentType in setOf("equal_payment", "equal_principal", "interest_only"))
    }
}
data class CashInput(val rentFee: Long?, val monthlyPayment: Long, val monthlyManagementFee: Long?)
data class SaleInput(val purchasePrice: Long, val annualGrowthRate: BigDecimal, val holdingYears: Int)
data class ScenarioInput(val purchasePrice: Long, val equity: Long, val annualGrowthRate: BigDecimal,
    val holdingYears: Int, val totalAcquisitionCost: Long, val totalInterest: Long, val rentFee: Long?, val rentDeposit: Long?,
    val jeonseOpportunityRate: BigDecimal = BigDecimal("3.5"), val ownedHomes: Int = 1, val officialPrice: Long = 0,
    val vacancyRate: BigDecimal = BigDecimal.ZERO, val residenceYears: Int? = null)
data class DsrInput(val loanAmount: Long, val annualInterestRate: BigDecimal, val loanYears: Int, val annualIncome: Long,
    val existingAnnualDebtPayment: Long = 0)
data class LtvInput(val purchasePrice: Long, val loanAmount: Long, val ownedHomes: Int = 1, val adjustedArea: Boolean = false)

/** 기존 AI 도구의 세부 계산 계약도 같은 엔진을 사용해 수식이 갈라지지 않게 한다. */
@Service
class CalculationPrimitives(private val calculator: FinanceCalculator, private val json: ObjectMapper) {
    fun calculate(operation: String, body: JsonNode): Any? = when (operation) {
        "calc_acquisition_tax", "calc_brokerage_fee", "calc_other_acquisition_cost", "calc_total_acquisition_cost" -> {
            val input = json.treeToValue(body, PriceInput::class.java)
            money(input.purchasePrice); requireInput(input.ownedHomes in 1..100)
            val cost = calculator.acquisition(input.purchasePrice, input.propertyType, input.ownedHomes)
            when (operation) {
                "calc_acquisition_tax" -> cost.acquisitionTax; "calc_brokerage_fee" -> cost.brokerageFee
                "calc_other_acquisition_cost" -> cost.otherCost; else -> cost
            }
        }
        "calc_monthly_payment", "calc_interest_during_holding", "calc_loan_summary" -> {
            val input = json.treeToValue(body, LoanInput::class.java).also { it.check() }
            when (operation) {
                "calc_monthly_payment" -> calculator.monthly(input.loanAmount, input.annualInterestRate, input.loanYears, input.repaymentType)
                "calc_interest_during_holding" -> calculator.interest(input.loanAmount, input.annualInterestRate, input.loanYears, input.holdingYears, input.repaymentType)
                else -> calculator.loan(input.loanAmount, input.annualInterestRate, input.loanYears, input.repaymentType)
            }
        }
        "calc_cash_flow" -> {
            val input = json.treeToValue(body, CashInput::class.java)
            val rent = input.rentFee ?: 0; val management = input.monthlyManagementFee ?: 0
            listOf(rent, input.monthlyPayment, management).forEach { money(it) }
            CashFlowSummary(rent, input.monthlyPayment, management, plusExact(rent, -input.monthlyPayment, -management))
        }
        "calc_expected_sale_price" -> {
            val input = json.treeToValue(body, SaleInput::class.java)
            money(input.purchasePrice); range(input.annualGrowthRate, "-100", "100"); requireInput(input.holdingYears in 0..100)
            calculator.salePrice(input.purchasePrice, input.annualGrowthRate, input.holdingYears)
        }
        "calc_scenario" -> {
            val value = json.treeToValue(body, ScenarioInput::class.java)
            val input = SimulationInput(purchasePrice = value.purchasePrice, holdingYears = value.holdingYears,
                rentFee = value.rentFee, rentDeposit = value.rentDeposit, ownedHomes = value.ownedHomes,
                jeonseOpportunityRate = value.jeonseOpportunityRate, vacancyRate = value.vacancyRate, residenceYears = value.residenceYears)
            input.check(); money(value.totalAcquisitionCost); money(value.totalInterest); money(value.officialPrice)
            requireInput(value.equity in -MONEY_LIMIT..MONEY_LIMIT); range(value.annualGrowthRate, "-100", "100")
            calculator.scenario(input, value.equity, value.totalAcquisitionCost, value.totalInterest, value.officialPrice, value.annualGrowthRate)
        }
        "check_ltv" -> {
            val value = json.treeToValue(body, LtvInput::class.java)
            money(value.purchasePrice, true); money(value.loanAmount); requireInput(value.ownedHomes in 1..100)
            val result = calculator.finance(SimulationInput(purchasePrice = value.purchasePrice, loanAmount = value.loanAmount,
                ownedHomes = value.ownedHomes, adjustedArea = value.adjustedArea))
            mapOf("ltv" to result.ltv, "limit" to result.ltvLimit, "exceeded" to result.ltvExceeded, "max_loan_amount" to result.ltvMaxLoan)
        }
        "check_dsr" -> {
            val value = json.treeToValue(body, DsrInput::class.java)
            LoanInput(value.loanAmount, value.annualInterestRate, value.loanYears).check()
            money(value.annualIncome); money(value.existingAnnualDebtPayment)
            val result = calculator.finance(SimulationInput(purchasePrice = maxOf(1, value.loanAmount), loanAmount = value.loanAmount,
                annualInterestRate = value.annualInterestRate, loanYears = value.loanYears,
                annualIncome = value.annualIncome, existingLoanAnnualPayment = value.existingAnnualDebtPayment))
            mapOf("dsr" to result.dsr, "limit" to result.dsrLimit, "stress_rate" to result.stressRate,
                "annual_payment" to result.dsrAnnualPayment, "exceeded" to result.dsrExceeded, "max_loan_amount" to result.dsrMaxLoan)
        }
        else -> null
    }
}
