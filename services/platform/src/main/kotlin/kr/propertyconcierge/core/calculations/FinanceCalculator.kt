package kr.propertyconcierge.core.calculations

import org.springframework.stereotype.Service
import java.math.BigDecimal
import kotlin.math.pow

@Service
class FinanceCalculator {
    private val commercial = setOf("상가", "오피스", "사무실", "업무용", "상업용", "공장", "창고", "산업용", "토지")
    private fun housing(type: String?) = commercial.none { (type ?: "").contains(it) }
    fun acquisition(price: Long, type: String?, homes: Int): AcquisitionCost {
        val rate = when {
            !housing(type) -> "0.044"; homes >= 3 -> "0.12"; homes == 2 -> "0.08"
            price <= 600_000_000 -> "0.011"; price <= 900_000_000 -> "0.022"; else -> "0.033"
        }
        val tax = (bd(price) * decimal(rate)).won()
        val fee = brokerage(price)
        val other = otherAcquisitionCost(price)
        return AcquisitionCost(tax, fee, other, plusExact(tax, fee, other))
    }
    fun otherAcquisitionCost(price: Long) = (bd(price) * decimal("0.001")).won().coerceIn(300_000, 2_000_000)
    fun salePrice(price: Long, growth: BigDecimal, years: Int) =
        (bd(price) * (BigDecimal.ONE + percent(growth)).pow(years, MC)).won()
    fun brokerage(price: Long): Long {
        val (rate, cap) = when {
            price <= 50_000_000 -> "0.006" to 250_000L
            price <= 200_000_000 -> "0.005" to 800_000L
            price <= 900_000_000 -> "0.004" to Long.MAX_VALUE
            price <= 1_200_000_000 -> "0.005" to Long.MAX_VALUE
            price <= 1_500_000_000 -> "0.006" to Long.MAX_VALUE
            else -> "0.007" to Long.MAX_VALUE
        }
        return (bd(price) * decimal(rate)).won().coerceAtMost(cap)
    }
    internal fun annuity(loan: Long, rate: BigDecimal, years: Int): BigDecimal {
        val months = bd(years * 12L)
        val r = percent(rate).divided(decimal("12"))
        if (r.signum() == 0) return bd(loan).divided(months)
        val power = (BigDecimal.ONE + r).pow(years * 12, MC)
        return (bd(loan) * r * power).divided(power - BigDecimal.ONE)
    }
    fun monthly(loan: Long, rate: BigDecimal, years: Int, type: String): Long {
        if (loan == 0L) return 0
        val r = percent(rate).divided(decimal("12"))
        return when (type) {
            "equal_payment" -> annuity(loan, rate, years).won()
            "equal_principal" -> (bd(loan).divided(bd(years * 12L)) + bd(loan) * r).won()
            "interest_only" -> (bd(loan) * r).won()
            else -> throw IllegalArgumentException("지원하지 않는 상환 방식입니다")
        }
    }
    fun interest(loan: Long, rate: BigDecimal, years: Int, holding: Int, type: String): Long {
        if (loan == 0L || rate.signum() == 0) return 0
        val r = percent(rate).divided(decimal("12"))
        val months = (holding * 12).coerceAtMost(years * 12)
        val principal = bd(loan).divided(bd(years * 12L))
        val payment = if (type == "equal_payment") annuity(loan, rate, years) else BigDecimal.ZERO
        var balance = bd(loan)
        var total = BigDecimal.ZERO
        // 잔액을 직접 누적하면 초저금리에서 지수식의 큰 수끼리 뺄 때 생기는 오차를 피할 수 있다.
        repeat(months) {
            val current = balance.multiply(r, MC)
            total = total.add(current, MC)
            when (type) {
                "equal_payment" -> balance = balance.subtract(payment - current, MC)
                "equal_principal" -> balance = balance.subtract(principal, MC)
                "interest_only" -> Unit
                else -> throw IllegalArgumentException("지원하지 않는 상환 방식입니다")
            }
        }
        return total.won()
    }
    fun loan(loan: Long, rate: BigDecimal, years: Int, type: String): LoanSummary {
        val monthly = monthly(loan, rate, years, type)
        if (loan == 0L || rate.signum() == 0) return LoanSummary(monthly, loan, 0)
        if (type == "equal_payment") {
            val total = Math.multiplyExact(monthly, years * 12L)
            return LoanSummary(monthly, total, total - loan)
        }
        val totalInterest = interest(loan, rate, years, years, type)
        return LoanSummary(monthly, plusExact(loan, totalInterest), totalInterest)
    }
    fun finance(input: SimulationInput): FinanceCheck {
        val limit = decimal(if (input.adjustedArea) { if (input.ownedHomes >= 2) "0.30" else "0.50" }
            else { if (input.ownedHomes >= 2) "0.60" else "0.70" })
        val ltv = bd(input.loanAmount).divided(bd(input.purchasePrice))
        val basic = FinanceCheck(ltv.rounded(4), limit, ltv > limit, (bd(input.purchasePrice) * limit).won())
        val income = input.annualIncome
        if (income == null || income == 0L || input.loanAmount == 0L) return basic
        val stress = input.annualInterestRate + decimal("1.5")
        val annual = (annuity(input.loanAmount, stress, input.loanYears) * decimal("12")).won()
        val dsr = bd(plusExact(annual, input.existingLoanAnnualPayment)).divided(bd(income))
        val maxAnnual = bd(income) * decimal("0.40") - bd(input.existingLoanAnnualPayment)
        val maxLoan = if (maxAnnual.signum() <= 0) 0L else
            (maxAnnual.divided(annuity(100_000_000, stress, input.loanYears) * decimal("12")) * bd(100_000_000)).won()
        return basic.copy(dsr = dsr.rounded(4), dsrExceeded = dsr > decimal("0.40"), stressRate = stress.rounded(2),
            dsrAnnualPayment = annual, dsrMaxLoan = maxLoan)
    }
    fun scenario(input: SimulationInput, equity: Long, cost: Long, interest: Long, official: Long,
        growth: BigDecimal): ScenarioResult {
        val multiplier = BigDecimal.ONE + percent(growth)
        val sale = salePrice(input.purchasePrice, growth, input.holdingYears)
        val capital = sale - input.purchasePrice
        val rent = input.rentFee ?: 0
        val deposit = input.rentDeposit ?: 0
        val annualRent = when {
            rent > 0 -> (bd(rent) * decimal("12") * (BigDecimal.ONE - percent(input.vacancyRate))).won()
            deposit > 0 -> (bd(deposit) * percent(input.jeonseOpportunityRate)).won()
            else -> 0L
        }
        val totalRent = Math.multiplyExact(annualRent, input.holdingYears.toLong())
        val saleFee = brokerage(sale)
        val homes = if (housing(input.propertyType)) input.ownedHomes else 99
        var holdingTax = 0L
        if (official > 0) for (year in 1..input.holdingYears) {
            val yearlyOfficial = (bd(official) * multiplier.pow(year, MC)).won()
            holdingTax = plusExact(holdingTax, TaxRules.holding(yearlyOfficial, homes).total)
        }
        // 임차인이 살고 있는 집을 승계하면 매수인이 거주한 기간으로 보지 않는다.
        val residence = input.residenceYears ?: if (rent > 0 || deposit > 0 || (input.assumedDeposit ?: 0) > 0) 0 else input.holdingYears
        val tax = TaxRules.capitalGains(input.purchasePrice, sale, input.holdingYears, homes, plusExact(cost, saleFee), residence)
        val preTax = plusExact(capital, totalRent, -interest, -cost)
        val net = plusExact(preTax, -tax.tax, -holdingTax, -saleFee)
        val infinite = equity <= 0
        val roi = if (infinite) 0.0 else (bd(net).divided(bd(equity)) * decimal("100")).rounded(2).toDouble()
        val value = plusExact(equity, net)
        val annualRoi = when {
            infinite -> 0.0; value <= 0 -> -100.0
            else -> BigDecimal.valueOf((bd(value).divided(bd(equity)).toDouble().pow(1.0 / input.holdingYears) - 1) * 100).rounded(2).toDouble()
        }
        return ScenarioResult(growth.rounded(2), sale, capital, totalRent, net, roi, annualRoi,
            (bd(annualRent).divided(bd(input.purchasePrice)) * decimal("100")).rounded(2).toDouble(),
            preTax, tax.tax, holdingTax, saleFee, tax.note, infinite)
    }
    fun calculate(input: SimulationInput): SimulationResult {
        input.check()
        val acquisition = acquisition(input.purchasePrice, input.propertyType, input.ownedHomes)
        // 승계 보증금은 매도인에게 주지 않고 임차인에게 돌려줄 의무를 넘겨받으므로 잔금에서 뺀다.
        val required = plusExact(input.purchasePrice, -input.loanAmount, acquisition.total, -(input.assumedDeposit ?: 0))
        val equity = required - (input.rentDeposit ?: 0)
        val loan = loan(input.loanAmount, input.annualInterestRate, input.loanYears, input.repaymentType)
        val rent = input.rentFee ?: 0
        val management = input.monthlyManagementFee ?: 0
        val cashFlow = CashFlowSummary(rent, loan.monthlyPayment, management, plusExact(rent, -loan.monthlyPayment, -management))
        val holdingInterest = interest(input.loanAmount, input.annualInterestRate, input.loanYears, input.holdingYears, input.repaymentType)
        val estimated = (input.officialPrice ?: 0) == 0L && housing(input.propertyType)
        val official = input.officialPrice?.takeIf { it > 0 } ?: if (estimated) TaxRules.official(input.purchasePrice) else 0
        fun scenarioAt(growth: BigDecimal, interestValue: Long = holdingInterest) = scenario(input, equity, acquisition.total, interestValue, official, growth)
        val rate = input.expectedAnnualGrowthRate
        val spread = input.scenarioSpread
        val base = scenarioAt(rate); val bull = scenarioAt(rate + spread); val bear = scenarioAt(rate - spread)
        var low = decimal("-20"); var high = decimal("50")
        var breakeven: BigDecimal? = null
        // 검색용 50% 경계의 장기 복리만 넘칠 때는 유효한 상한으로 좁힌다.
        // 사용자가 요청한 세 시나리오의 오버플로는 위에서 그대로 거부한다.
        for (attempt in 0 until 40) {
            try { scenarioAt(high); break } catch (_: ArithmeticException) {
                high = (low + high).divided(decimal("2"))
            }
        }
        if (scenarioAt(low).netProfit < 0 && scenarioAt(high).netProfit >= 0) {
            repeat(40) {
                val mid = (low + high).divided(decimal("2"))
                if (scenarioAt(mid).netProfit < 0) low = mid else high = mid
            }
            breakeven = high.rounded(2)
        }
        val sensitivity = listOf(rate - spread, rate, rate + spread).flatMap { growth ->
            listOf(decimal("-1"), BigDecimal.ZERO, BigDecimal.ONE).map { delta ->
                val variedRate = (input.annualInterestRate + delta).max(BigDecimal.ZERO)
                val variedInterest = interest(input.loanAmount, variedRate, input.loanYears, input.holdingYears, input.repaymentType)
                val result = scenarioAt(growth, variedInterest)
                RateSensitivityCell(growth.rounded(2), variedRate.rounded(2), result.annualEquityRoi, result.netProfit)
            }
        }
        return SimulationResult(input.purchasePrice, input.loanAmount, input.ownedHomes, equity = equity, requiredCash = required,
            acquisitionCost = acquisition, loan = loan, cashFlow = cashFlow, scenarioBase = base, scenarioBull = bull, scenarioBear = bear,
            officialPriceUsed = official, officialPriceEstimated = estimated, financeCheck = finance(input),
            breakevenGrowthRate = breakeven, rateSensitivity = sensitivity)
    }
}
