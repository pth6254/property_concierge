package kr.propertyconcierge.core.calculations

import java.math.BigDecimal
import java.math.MathContext
import java.math.RoundingMode

internal val MC = MathContext(34, RoundingMode.HALF_EVEN)
internal fun bd(value: Long) = BigDecimal.valueOf(value)
internal fun decimal(value: String) = BigDecimal(value)
internal fun BigDecimal.divided(other: BigDecimal) = divide(other, MC)
internal fun BigDecimal.won(): Long = setScale(0, RoundingMode.HALF_EVEN).longValueExact()
internal fun BigDecimal.rounded(places: Int) = setScale(places, RoundingMode.HALF_EVEN)
internal fun percent(value: BigDecimal) = value.divided(decimal("100"))
internal fun plusExact(vararg values: Long) = values.fold(0L, Math::addExact)
