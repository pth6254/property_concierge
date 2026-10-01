package kr.propertyconcierge.core.calculations

import java.math.BigDecimal

data class CapitalGainsTax(val tax: Long, val nationalTax: Long, val localTax: Long, val taxableGain: Long,
    val ltsdRate: BigDecimal, val exempt: Boolean, val note: String)
data class HoldingTax(val propertyTax: Long, val urbanTax: Long, val eduTax: Long, val jongbuTax: Long, val nongteuk: Long, val total: Long)
data class GiftTax(val tax: Long, val grossTax: Long, val reportCredit: Long, val deduction: Long, val taxable: Long, val note: String)
data class InheritanceTax(val tax: Long, val grossTax: Long, val reportCredit: Long, val deduction: Long,
    val spouseDeduction: Long, val taxable: Long, val note: String)

// 기존 간이 정책을 이전한다. 이 기준일은 최신 법령·은행 심사 조건을 검증했다는 뜻이 아니다.
object TaxRules {
    const val AS_OF = "2026-01-01"
    private data class Bracket(val limit: Long, val rate: String, val deduction: Long = 0)
    private val capitalBrackets = listOf(
        Bracket(14_000_000, "0.06"), Bracket(50_000_000, "0.15", 1_260_000), Bracket(88_000_000, "0.24", 5_760_000),
        Bracket(150_000_000, "0.35", 15_440_000), Bracket(300_000_000, "0.38", 19_940_000),
        Bracket(500_000_000, "0.40", 25_940_000), Bracket(1_000_000_000, "0.42", 35_940_000), Bracket(Long.MAX_VALUE, "0.45", 65_940_000))
    private val estateBrackets = listOf(Bracket(100_000_000, "0.10"), Bracket(500_000_000, "0.20", 10_000_000),
        Bracket(1_000_000_000, "0.30", 60_000_000), Bracket(3_000_000_000, "0.40", 160_000_000), Bracket(Long.MAX_VALUE, "0.50", 460_000_000))
    private fun progressive(base: Long, brackets: List<Bracket>): Long {
        val bracket = brackets.first { base <= it.limit }
        return (bd(base) * decimal(bracket.rate) - bd(bracket.deduction)).won().coerceAtLeast(0)
    }
    fun capitalGains(purchase: Long, sale: Long, years: Int, homes: Int = 1, expenses: Long = 0, residence: Int = 0): CapitalGainsTax {
        var gain = sale - purchase - expenses
        fun zero(note: String, exempt: Boolean = false, ltsd: BigDecimal = BigDecimal.ZERO) = CapitalGainsTax(0, 0, 0, 0, ltsd, exempt, note)
        if (gain <= 0) return zero("양도차익 없음")
        val single = homes <= 1
        var note: String
        if (single && years >= 2) {
            if (sale <= 1_200_000_000) return zero("1세대1주택 비과세 (양도가 12억 이하)", true)
            gain = (bd(gain) * bd(sale - 1_200_000_000).divided(bd(sale))).won()
            note = "1세대1주택 고가주택 — 12억 초과분 과세"
        } else {
            note = if (single) "일반 과세" else "${homes}주택 보유 과세 (다주택 중과 유예 적용)"
        }
        val ltsd = if (years < 3) BigDecimal.ZERO else if (single && residence >= 2)
            (bd(years.coerceAtMost(10).toLong()) * decimal("0.04") + bd(residence.coerceAtMost(10).toLong()) * decimal("0.04")).min(decimal("0.80"))
            else (bd(years.coerceAtMost(15).toLong()) * decimal("0.02")).min(decimal("0.30"))
        val taxable = (bd(gain) * (BigDecimal.ONE - ltsd)).won() - 2_500_000
        if (taxable <= 0) return zero(note + " — 공제 후 과표 없음", ltsd = ltsd)
        val national = when {
            years < 1 -> { note += " · 단기양도 70%"; (bd(taxable) * decimal("0.70")).won() }
            years < 2 -> { note += " · 단기양도 60%"; (bd(taxable) * decimal("0.60")).won() }
            else -> progressive(taxable, capitalBrackets)
        }
        val local = (bd(national) * decimal("0.10")).won()
        return CapitalGainsTax(plusExact(national, local), national, local, taxable, ltsd, false, note)
    }
    fun holding(official: Long, homes: Int = 1): HoldingTax {
        if (official <= 0) return HoldingTax(0, 0, 0, 0, 0, 0)
        val single = homes <= 1
        val ratio = when { !single -> "0.60"; official <= 300_000_000 -> "0.43"; official <= 600_000_000 -> "0.44"; else -> "0.45" }
        val base = (bd(official) * decimal(ratio)).won()
        val special = single && official <= 900_000_000
        val brackets = if (special) listOf(Bracket(60_000_000, "0.0005"), Bracket(150_000_000, "0.0010", 30_000),
            Bracket(300_000_000, "0.0020", 180_000), Bracket(Long.MAX_VALUE, "0.0035", 630_000))
            else listOf(Bracket(60_000_000, "0.0010"), Bracket(150_000_000, "0.0015", 30_000),
                Bracket(300_000_000, "0.0025", 180_000), Bracket(Long.MAX_VALUE, "0.0040", 630_000))
        val property = progressive(base, brackets)
        val urban = (bd(base) * decimal("0.0014")).won()
        val education = (bd(property) * decimal("0.20")).won()
        val deduction = if (single) 1_200_000_000L else 900_000_000L
        var jongbu = 0L
        if (official > deduction) {
            val jbBase = (bd(official - deduction) * decimal("0.60")).won()
            val rates = if (homes <= 2) listOf("0.005", "0.007", "0.010", "0.013", "0.015", "0.020", "0.027")
                else listOf("0.005", "0.007", "0.010", "0.020", "0.030", "0.040", "0.050")
            val limits = listOf(300_000_000L, 600_000_000L, 1_200_000_000L, 2_500_000_000L, 5_000_000_000L, 9_400_000_000L, Long.MAX_VALUE)
            var previous = 0L
            var total = BigDecimal.ZERO
            for ((limit, rate) in limits.zip(rates)) {
                if (jbBase <= previous) break
                total += bd(jbBase.coerceAtMost(limit) - previous) * decimal(rate)
                previous = limit
            }
            jongbu = total.won()
        }
        val nongteuk = (bd(jongbu) * decimal("0.20")).won()
        return HoldingTax(property, urban, education, jongbu, nongteuk, plusExact(property, urban, education, jongbu, nongteuk))
    }
    fun official(market: Long) = (bd(market) * decimal("0.69")).won()
    fun gift(value: Long, relation: String = "직계존속", prior: Long = 0, marriage: Boolean = false): GiftTax {
        var deduction = mapOf("배우자" to 600_000_000L, "직계존속" to 50_000_000L, "직계존속미성년" to 20_000_000L,
            "직계비속" to 50_000_000L, "기타친족" to 10_000_000L, "타인" to 0L)[relation] ?: 0L
        if (marriage && relation.startsWith("직계존속")) deduction += 100_000_000
        val taxable = (plusExact(value, prior) - deduction).coerceAtLeast(0)
        val gross = (progressive(taxable, estateBrackets) - progressive((prior - deduction).coerceAtLeast(0), estateBrackets)).coerceAtLeast(0)
        val credit = (bd(gross) * decimal("0.03")).won()
        val note = "$relation 공제 ${"%,d".format(java.util.Locale.ROOT, deduction)}원" +
            (if (prior > 0) " · 10년 합산 ${"%,d".format(java.util.Locale.ROOT, prior)}원 반영" else "") + " · 신고세액공제 3%"
        return GiftTax(gross - credit, gross, credit, deduction, taxable, note)
    }
    fun inheritance(value: Long, spouse: Boolean = true, share: Long = 0, debts: Long = 0): InheritanceTax {
        val spouseDeduction = if (spouse) share.coerceIn(500_000_000, 3_000_000_000) else 0L
        val deduction = spouseDeduction + 500_000_000
        val taxable = (value - debts - deduction).coerceAtLeast(0)
        val gross = progressive(taxable, estateBrackets)
        val credit = (bd(gross) * decimal("0.03")).won()
        val note = "일괄공제 5억" + (if (spouseDeduction > 0) " + 배우자공제 ${"%,d".format(java.util.Locale.ROOT, spouseDeduction)}원" else "") + " · 신고세액공제 3%"
        return InheritanceTax(gross - credit, gross, credit, deduction, spouseDeduction, taxable, note)
    }
}
