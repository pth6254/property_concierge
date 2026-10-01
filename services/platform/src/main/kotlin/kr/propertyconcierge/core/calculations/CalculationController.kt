package kr.propertyconcierge.core.calculations

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import com.fasterxml.jackson.annotation.JsonProperty
import kr.propertyconcierge.core.ApiFailure
import org.springframework.core.env.Environment
import org.springframework.web.bind.annotation.*
import java.security.MessageDigest

data class GiftInput(val giftValue: Long, val relation: String = "직계존속",
    @param:JsonProperty("prior_gifts_10yr") val priorGifts10yr: Long = 0, val marriageDeduction: Boolean = false)
data class InheritanceInput(val estateValue: Long, val hasSpouse: Boolean = true, val spouseShare: Long = 0, val debts: Long = 0)
data class CapitalInput(val purchasePrice: Long, val salePrice: Long, val holdingYears: Int, val ownedHomes: Int = 1,
    val expenses: Long = 0, val residenceYears: Int = 0)
data class HoldingInput(val officialPrice: Long, val ownedHomes: Int = 1)
data class OfficialInput(val marketPrice: Long)

@RestController
@RequestMapping("/internal/v1/calculations")
class CalculationController(private val calculator: FinanceCalculator, private val primitives: CalculationPrimitives,
    private val json: ObjectMapper, env: Environment) {
    private val key = env.getRequiredProperty("INTERNAL_SERVICE_SECRET").also { require(it.length >= 32) }
    @PostMapping("/{operation}")
    fun calculate(@PathVariable operation: String, @RequestBody body: JsonNode,
        @RequestHeader("X-Internal-Service-Key", required = false) provided: String?): Any {
        if (provided == null || !MessageDigest.isEqual(key.toByteArray(), provided.toByteArray()))
            throw ApiFailure(401, "내부 서비스 인증이 필요합니다")
        try {
            return when (operation) {
                "simulation" -> calculator.calculate(json.treeToValue(body, SimulationInput::class.java))
                "funding_summary" -> json.treeToValue(body, FundingSummaryInput::class.java).let {
                    val input = it.request.input()
                    requireInput(it.calculated.purchasePrice == input.purchasePrice && it.calculated.loanAmount == input.loanAmount &&
                        it.calculated.ownedHomes == input.ownedHomes && it.calculated.calculatorEngine == "kotlin-spring")
                    it.request.summary(it.calculated, json)
                }
                "calc_gift_tax" -> json.treeToValue(body, GiftInput::class.java).let {
                    money(it.giftValue); money(it.priorGifts10yr); requireInput(it.relation.length <= 50)
                    TaxRules.gift(it.giftValue, it.relation, it.priorGifts10yr, it.marriageDeduction)
                }
                "calc_inheritance_tax" -> json.treeToValue(body, InheritanceInput::class.java).let {
                    money(it.estateValue); money(it.spouseShare); money(it.debts)
                    TaxRules.inheritance(it.estateValue, it.hasSpouse, it.spouseShare, it.debts)
                }
                "calc_capital_gains_tax" -> json.treeToValue(body, CapitalInput::class.java).let {
                    money(it.purchasePrice, true); money(it.salePrice); money(it.expenses)
                    requireInput(it.holdingYears in 0..100 && it.residenceYears in 0..100 && it.ownedHomes in 1..100)
                    TaxRules.capitalGains(it.purchasePrice, it.salePrice, it.holdingYears, it.ownedHomes, it.expenses, it.residenceYears)
                }
                "calc_annual_holding_tax" -> json.treeToValue(body, HoldingInput::class.java).let {
                    money(it.officialPrice); requireInput(it.ownedHomes in 1..100); TaxRules.holding(it.officialPrice, it.ownedHomes)
                }
                "estimate_official_price" -> json.treeToValue(body, OfficialInput::class.java).let { money(it.marketPrice); TaxRules.official(it.marketPrice) }
                else -> primitives.calculate(operation, body) ?: throw ApiFailure(404, "계산 경로가 없습니다")
            }
        } catch (_: ArithmeticException) {
            // 장기 복리 등으로 64비트 원 단위를 넘으면 값을 잘라 저장하지 않고 입력 보완을 요청한다.
            throw ApiFailure(422, "예상 금액이 계산 범위를 초과합니다. 금액·기간·상승률을 조정해주세요")
        }
    }
}
