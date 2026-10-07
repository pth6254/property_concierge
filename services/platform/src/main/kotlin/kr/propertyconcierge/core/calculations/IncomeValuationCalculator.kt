package kr.propertyconcierge.core.calculations

import kr.propertyconcierge.core.ApiFailure
import org.springframework.stereotype.Service
import java.math.BigDecimal
import java.time.LocalDate
import java.time.ZoneId

data class IncomeValuationInput(
    val monthlyRentWon: Long,
    val monthlyOperatingCostMinWon: Long?,
    val monthlyOperatingCostMaxWon: Long?,
    val capRateMinPct: BigDecimal,
    val capRateMaxPct: BigDecimal,
    val askingPriceWon: Long? = null,
    val valuationUnit: String,
    val asOfDate: String,
)

@Service
class IncomeValuationCalculator {
    fun calculate(input: IncomeValuationInput): Map<String, Any?> {
        fun check(ok: Boolean) { if (!ok) throw ApiFailure(422, "임대료·운영비 범위·환원율·기준일을 확인해주세요") }
        fun amount(value: Long) = check(value in 0..1_000_000_000_000_000L)
        amount(input.monthlyRentWon)
        input.askingPriceWon?.let { amount(it); check(it > 0) }
        check(input.valuationUnit in setOf("single_unit", "whole_building"))
        val date = try { LocalDate.parse(input.asOfDate) } catch (_: Exception) { throw ApiFailure(422, "임대료 확인일을 확인해주세요") }
        check(!date.isAfter(LocalDate.now(ZoneId.of("Asia/Seoul"))))
        val lowCap = input.capRateMinPct
        val highCap = input.capRateMaxPct
        check(lowCap >= decimal("0.1") && highCap <= decimal("100") && lowCap <= highCap)
        check(lowCap.scale() <= 4 && highCap.scale() <= 4)
        val minCost = input.monthlyOperatingCostMinWon
        val maxCost = input.monthlyOperatingCostMaxWon
        check((minCost == null) == (maxCost == null))
        if (minCost != null && maxCost != null) { amount(minCost); amount(maxCost); check(minCost <= maxCost) }
        // 현재 수령 월세에는 이미 공실 영향이 반영된다. 공실률·보증금 원금·대출 비용을 다시 차감하지 않는다.
        val annualRent = bd(input.monthlyRentWon).multiply(decimal("12"), MC)
        val minNoi = maxCost?.let { annualRent.subtract(bd(it).multiply(decimal("12"), MC)) }
        val maxNoi = minCost?.let { annualRent.subtract(bd(it).multiply(decimal("12"), MC)) }
        val usable = minNoi != null && maxNoi != null && minNoi.signum() > 0
        fun yield(value: BigDecimal?) = if (value != null && input.askingPriceWon != null)
            value.divided(bd(input.askingPriceWon)).multiply(decimal("100"), MC).rounded(4) else null
        val scenarios = if (usable) listOf(lowCap, lowCap.add(highCap).divided(decimal("2")), highCap).distinct().map { cap ->
            mapOf("cap_rate_pct" to cap, "low_price_won" to requireNotNull(minNoi).divided(percent(cap)).won(),
                "high_price_won" to requireNotNull(maxNoi).divided(percent(cap)).won())
        } else emptyList()
        return mapOf(
            "result_kind" to if (usable) "conditional_scenario" else "withheld",
            "calculator_engine" to "kotlin-spring", "calculation_version" to "income-scenario-1.0",
            "currency" to "KRW", "inputs" to input, "income_basis" to "current_received_rent",
            "cap_rate_source" to "user_assumption", "annual_rent_won" to annualRent.won(),
            "annual_noi_min_won" to minNoi?.won(), "annual_noi_max_won" to maxNoi?.won(),
            "gross_yield_pct" to yield(annualRent), "net_yield_min_pct" to yield(minNoi), "net_yield_max_pct" to yield(maxNoi),
            "low_price_won" to if (usable) requireNotNull(minNoi).divided(percent(highCap)).won() else null,
            "high_price_won" to if (usable) requireNotNull(maxNoi).divided(percent(lowCap)).won() else null,
            "scenarios" to scenarios,
            "limitations" to listOfNotNull(
                "사용자 입력 임대료와 환원율 가정에 따른 시나리오이며 시장가격 검증·법정 감정평가가 아닙니다.",
                "현재 월세의 연 환산입니다. 향후 계약 변경·공실·대수선·세금·대출 상환 및 보증금 운용수익은 반영하지 않습니다.",
                if (minCost == null) "운영비가 미입력되어 NOI와 가격 범위를 산출하지 않았습니다." else null,
                if (minNoi != null && minNoi.signum() <= 0) "순영업소득 범위에 0 이하가 포함되어 수익환원 가격을 보류했습니다. 자산 가치가 0이라는 뜻은 아닙니다." else null,
            ),
        )
    }
}
