package kr.propertyconcierge.core.store

import jakarta.validation.Valid
import jakarta.validation.constraints.*
import kr.propertyconcierge.core.ApiFailure

data class BuyerProfileInput(
    @field:Min(0) @field:Max(1000000000000000) val cashAvailable: Long? = null,
    @field:Min(0) @field:Max(1000000000000000) val emergencyReserve: Long = 0,
    @field:Min(0) @field:Max(1000000000000) val monthlyPaymentLimit: Long? = null,
    @field:Min(0) @field:Max(1000000000000000) val annualIncome: Long? = null,
    @field:Min(0) @field:Max(1000000000000000) val existingLoanAnnualPayment: Long = 0,
    @field:DecimalMin("0") @field:DecimalMax("0.9") val loanRatio: Double? = null,
    @field:DecimalMin("0") @field:DecimalMax("30") val annualInterestRate: Double? = null,
    @field:Min(1) @field:Max(50) val loanYears: Int? = null,
    @field:Min(1) @field:Max(100) val ownedHomes: Int? = null,
    val adjustedArea: Boolean? = null,
    @field:DecimalMin(value="0", inclusive=false) @field:DecimalMax("100000") val minAreaSqm: Double? = null,
    @field:DecimalMin(value="0", inclusive=false) @field:DecimalMax("100000") val maxAreaSqm: Double? = null,
    @field:Min(1800) @field:Max(2100) val minBuildYear: Int? = null,
    @field:Min(1800) @field:Max(2100) val maxBuildYear: Int? = null,
    @field:Min(1) @field:Max(60) val marketMonths: Int = 12,
    @field:Size(max=7) val propertyTypes: List<String> = emptyList(),
    @field:Pattern(regexp="cash|monthly|value|liquidity|age") val priority: String = "cash"
) {
    fun check() {
        if ((cashAvailable != null && emergencyReserve > cashAvailable) ||
            (minAreaSqm != null && maxAreaSqm != null && minAreaSqm > maxAreaSqm) ||
            (minBuildYear != null && maxBuildYear != null && minBuildYear > maxBuildYear) ||
            listOfNotNull(loanRatio, annualInterestRate, minAreaSqm, maxAreaSqm).any { !it.isFinite() } ||
            propertyTypes.any { it !in setOf("apartment", "officetel", "row_house", "detached", "non_residential", "industrial", "land") })
            throw ApiFailure(422, "매수 조건의 범위와 비상자금을 확인해주세요")
    }
}

data class CaseCreateInput(@field:Size(min=1,max=150) val title: String,
    @field:Min(0) val budgetMin: Long? = null, @field:Min(0) val budgetMax: Long? = null,
    @field:Size(max=20) val targetRegions: List<String> = emptyList(), @field:Size(max=5000) val notes: String = "",
    @field:Valid val buyerProfile: BuyerProfileInput = BuyerProfileInput())

data class CaseUpdateInput(@field:Size(min=1,max=150) val title: String? = null,
    @field:Pattern(regexp="exploring|reviewing|negotiating|decided|archived") val status: String? = null,
    @field:Min(0) val budgetMin: Long? = null, @field:Min(0) val budgetMax: Long? = null,
    @field:Size(max=20) val targetRegions: List<String>? = null, @field:Size(max=5000) val notes: String? = null,
    @field:Valid val buyerProfile: BuyerProfileInput? = null)

data class PropertyIdentityInput(@field:Size(max=30) val buildingDong: String = "",
    @field:Size(max=30) val unitNumber: String = "", @field:Size(max=30) val floor: String = "",
    @field:Pattern(regexp="exclusive|supply|unknown") val areaBasis: String = "unknown")

data class PropertyCreateInput(@field:Size(min=1,max=150) val name: String,
    @field:Size(max=500) val address: String = "", @field:Size(max=30) val category: String = "",
    @field:Min(0) val askingPrice: Long? = null, @field:DecimalMin(value="0",inclusive=false) val areaSqm: Double? = null,
    @field:Pattern(regexp="[0-9]{10}") val legalRegionCode: String? = null,
    @field:Pattern(regexp="manual|recommendation|appraisal") val source: String = "manual",
    @field:Pattern(regexp="reviewing|shortlisted|rejected|selected") val status: String = "reviewing",
    @field:Size(max=5000) val notes: String = "", @field:Min(1) val historyId: Long? = null,
    @field:Valid val identity: PropertyIdentityInput = PropertyIdentityInput())

data class PropertyUpdateInput(@field:Min(0) val askingPrice: Long? = null,
    @field:Pattern(regexp="reviewing|shortlisted|rejected|selected") val status: String? = null,
    @field:Size(max=5000) val notes: String? = null, @field:Valid val identity: PropertyIdentityInput? = null)

data class ChecklistInput(@field:Pattern(regexp="todo|done|warning|blocked") val status: String,
    @field:Size(max=5000) val evidence: String? = null)
data class DecisionInput(@field:Min(1) val propertyId: Long, @field:Size(min=3,max=5000) val reason: String)
data class SourceApplyInput(@field:Min(1) val expectedRevisionId: Long, @field:NotBlank val expectedConfirmedAt: String)
data class CandidateTargetInput(@field:Min(1) val caseId: Long)

data class ExecutionPlanInput(@field:Pattern(regexp="[0-9]{4}-[0-9]{2}-[0-9]{2}") val contractPlannedDate: String? = null,
    @field:Pattern(regexp="[0-9]{4}-[0-9]{2}-[0-9]{2}") val closingPlannedDate: String? = null)
data class ExecutionTaskInput(@field:Pattern(regexp="before_contract|before_closing|closing_day|after_closing") val phase: String,
    @field:Size(min=1,max=200) val title: String, @field:Size(max=5000) val description: String = "",
    @field:Pattern(regexp="self|bank|broker|legal_agent|tax_agent|other") val actorType: String = "self",
    val required: Boolean = false, @field:Pattern(regexp="[0-9]{4}-[0-9]{2}-[0-9]{2}") val dueDate: String? = null)
data class ExecutionTaskUpdateInput(@field:Pattern(regexp="scheduled|in_progress|waiting_external|done|problem|not_applicable") val status: String? = null,
    @field:Pattern(regexp="self|bank|broker|legal_agent|tax_agent|other") val actorType: String? = null,
    @field:Pattern(regexp="[0-9]{4}-[0-9]{2}-[0-9]{2}") val dueDate: String? = null,
    @field:Size(max=150) val checkedBy: String? = null, @field:Size(max=5000) val outcome: String? = null,
    @field:Size(max=5000) val evidenceNote: String? = null, @field:Size(max=5000) val followUp: String? = null)
