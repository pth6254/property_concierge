package kr.propertyconcierge.core.store

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import com.fasterxml.jackson.databind.node.ObjectNode
import jakarta.servlet.http.HttpServletRequest
import jakarta.servlet.http.HttpServletResponse
import jakarta.validation.Valid
import jakarta.validation.Validator
import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.CoreUsageMetrics
import kr.propertyconcierge.core.auth.SessionService
import kr.propertyconcierge.core.bridge.PythonClient
import org.springframework.http.HttpStatus
import org.springframework.web.bind.annotation.*

@RestController
class CaseController(private val sessions: SessionService, private val store: CaseStore, private val execution: ExecutionStore,
    private val json: ObjectMapper, private val validator: Validator, private val python: PythonClient, private val metrics: CoreUsageMetrics) {
    private fun args(request: HttpServletRequest, caseId: Long? = null, extra: Map<String, Any?> = emptyMap()): JsonNode =
        json.valueToTree(mapOf("user_id" to sessions.required(request).id) + (caseId?.let { mapOf("case_id" to it) } ?: emptyMap()) + extra)
    private fun result(value: Any?): Any = value ?: throw ApiFailure(404, "검토 케이스 또는 후보가 없습니다")
    private fun stored(operation: String, request: HttpServletRequest, caseId: Long? = null, extra: Map<String, Any?> = emptyMap()): Any {
        val values = args(request, caseId, extra)
        val result = result(store.dispatch(operation, values))
        val step = mapOf("create_case" to "case_created", "add_property" to "candidate_added", "select_final_candidate" to "candidate_selected")[operation]
        if (step != null) metrics.step(step, values.path("user_id").asLong())
        if (operation == "update_case" && values.path("data").has("buyer_profile")) metrics.step("conditions_saved", values.path("user_id").asLong())
        return result
    }
    private fun executed(operation: String, request: HttpServletRequest, caseId: Long, extra: Map<String, Any?> = emptyMap()) =
        result(execution.dispatch(operation, args(request, caseId, extra)))
    private fun <T : Any> checked(body: JsonNode, type: Class<T>, nonNull: Set<String> = emptySet()): T {
        if (!body.isObject || nonNull.any { body.has(it) && body.path(it).isNull }) throw ApiFailure(422, "빈 값으로 변경할 수 없는 항목입니다")
        val input = json.treeToValue(body, type)
        if (validator.validate(input).isNotEmpty()) throw ApiFailure(422, "입력값의 범위와 형식을 확인해주세요")
        return input
    }
    @PostMapping("/api/cases") @ResponseStatus(HttpStatus.CREATED)
    fun create(request: HttpServletRequest, @Valid @RequestBody body: CaseCreateInput): Any {
        body.buyerProfile.check()
        if (body.budgetMin != null && body.budgetMax != null && body.budgetMin > body.budgetMax) throw ApiFailure(422, "예산 범위를 확인해주세요")
        return stored("create_case", request, extra=mapOf("data" to body))
    }
    @GetMapping("/api/cases")
    fun list(request: HttpServletRequest) = mapOf("items" to stored("list_cases", request))
    @GetMapping("/api/cases/{caseId:[0-9]+}")
    fun get(request: HttpServletRequest, @PathVariable caseId: Long) = stored("get_case", request, caseId)
    @PatchMapping("/api/cases/{caseId:[0-9]+}")
    fun update(request: HttpServletRequest, @PathVariable caseId: Long, @RequestBody body: JsonNode): Any {
        checked(body, CaseUpdateInput::class.java, setOf("title", "status", "notes", "target_regions", "buyer_profile")).buyerProfile?.check()
        return stored("update_case", request, caseId, mapOf("data" to body))
    }
    @DeleteMapping("/api/cases/{caseId:[0-9]+}") @ResponseStatus(HttpStatus.NO_CONTENT)
    fun delete(request: HttpServletRequest, @PathVariable caseId: Long) {
        if (stored("delete_case", request, caseId) != true) throw ApiFailure(404, "검토 케이스가 없습니다")
    }
    @GetMapping("/api/cases/{caseId:[0-9]+}/summary")
    fun summary(request: HttpServletRequest, @PathVariable caseId: Long): Map<String, Any> {
        val case = get(request, caseId)
        val assessed = python.analyze("decision/assess", mapOf("case" to case))
        return mapOf("case" to case, "comparison" to assessed.path("comparison"), "decision" to assessed.path("decision"))
    }
    @GetMapping("/api/cases/{caseId:[0-9]+}/comparison")
    fun comparison(request: HttpServletRequest, @PathVariable caseId: Long,
        @RequestParam(name="property_id",required=false) propertyIds: List<Long>?): JsonNode {
        val case = get(request, caseId)
        val assessed = python.analyze("decision/assess", mapOf("case" to case, "property_ids" to propertyIds)).path("comparison")
        if (assessed.path("rows").isEmpty) throw ApiFailure(422, "검토할 후보를 1개 이상 선택해주세요")
        metrics.step("comparison_viewed", sessions.required(request).id)
        return assessed
    }
    @PostMapping("/api/cases/{caseId:[0-9]+}/properties") @ResponseStatus(HttpStatus.CREATED)
    fun addProperty(request: HttpServletRequest, @PathVariable caseId: Long, @Valid @RequestBody body: PropertyCreateInput) =
        stored("add_property", request, caseId, mapOf("data" to body))
    @PatchMapping("/api/cases/{caseId:[0-9]+}/properties/{propertyId:[0-9]+}")
    fun updateProperty(request: HttpServletRequest, @PathVariable caseId: Long, @PathVariable propertyId: Long, @RequestBody body: JsonNode): Any {
        checked(body, PropertyUpdateInput::class.java, setOf("status", "notes", "identity"))
        return stored("update_property", request, caseId, mapOf("property_id" to propertyId, "data" to body))
    }
    @DeleteMapping("/api/cases/{caseId:[0-9]+}/properties/{propertyId:[0-9]+}") @ResponseStatus(HttpStatus.NO_CONTENT)
    fun deleteProperty(request: HttpServletRequest, @PathVariable caseId: Long, @PathVariable propertyId: Long) {
        if (stored("delete_property", request, caseId, mapOf("property_id" to propertyId)) != true) throw ApiFailure(404, "검토 후보가 없습니다")
    }
    @PatchMapping("/api/cases/{caseId:[0-9]+}/properties/{propertyId:[0-9]+}/checklist/{checklistId:[0-9]+}")
    fun checklist(request: HttpServletRequest, @PathVariable caseId: Long, @PathVariable propertyId: Long,
        @PathVariable checklistId: Long, @Valid @RequestBody body: ChecklistInput) =
        stored("update_checklist", request, caseId, mapOf("property_id" to propertyId, "checklist_id" to checklistId,
            "data" to (mapOf("status" to body.status) + (body.evidence?.let { mapOf("evidence" to it) } ?: emptyMap()))))
    @PostMapping("/api/cases/{caseId:[0-9]+}/decision")
    fun select(request: HttpServletRequest, @PathVariable caseId: Long, @Valid @RequestBody body: DecisionInput) =
        stored("select_final_candidate", request, caseId, mapOf("property_id" to body.propertyId, "reason" to body.reason))
    @DeleteMapping("/api/cases/{caseId:[0-9]+}/decision")
    fun clear(request: HttpServletRequest, @PathVariable caseId: Long) = stored("clear_final_candidate", request, caseId)
    @PostMapping("/api/cases/{caseId:[0-9]+}/properties/{propertyId:[0-9]+}/source-update")
    fun sourceUpdate(request: HttpServletRequest, @PathVariable caseId: Long, @PathVariable propertyId: Long, @Valid @RequestBody body: SourceApplyInput) =
        stored("apply_listing_update", request, caseId, mapOf("property_id" to propertyId, "expected_revision_id" to body.expectedRevisionId, "expected_confirmed_at" to body.expectedConfirmedAt))
    @PostMapping("/api/listings/{listingId:[0-9]+}/candidate")
    fun listingCandidate(request: HttpServletRequest, response: HttpServletResponse, @PathVariable listingId: Long, @Valid @RequestBody body: CandidateTargetInput): Any {
        val candidate = stored("add_property", request, body.caseId, mapOf("data" to mapOf("source_listing_id" to listingId))) as ObjectNode
        response.status = if (candidate.path("_already_linked").asBoolean()) 200 else 201
        candidate.remove("_already_linked")
        return candidate
    }
    @GetMapping("/api/cases/{caseId:[0-9]+}/execution")
    fun getExecution(request: HttpServletRequest, @PathVariable caseId: Long) = executed("get_execution", request, caseId)
    @PatchMapping("/api/cases/{caseId:[0-9]+}/execution")
    fun updateExecution(request: HttpServletRequest, @PathVariable caseId: Long, @RequestBody body: JsonNode): Any {
        checked(body, ExecutionPlanInput::class.java)
        return executed("update_plan", request, caseId, mapOf("data" to body))
    }
    @PostMapping("/api/cases/{caseId:[0-9]+}/execution/tasks") @ResponseStatus(HttpStatus.CREATED)
    fun addTask(request: HttpServletRequest, @PathVariable caseId: Long, @Valid @RequestBody body: ExecutionTaskInput) = executed("add_task", request, caseId, mapOf("data" to body))
    @PatchMapping("/api/cases/{caseId:[0-9]+}/execution/tasks/{taskId:[0-9]+}")
    fun updateTask(request: HttpServletRequest, @PathVariable caseId: Long, @PathVariable taskId: Long, @RequestBody body: JsonNode): Any {
        checked(body, ExecutionTaskUpdateInput::class.java, setOf("status", "actor_type", "checked_by", "outcome", "evidence_note", "follow_up"))
        return executed("update_task", request, caseId, mapOf("task_id" to taskId, "data" to body))
    }
    @DeleteMapping("/api/cases/{caseId:[0-9]+}/execution/tasks/{taskId:[0-9]+}") @ResponseStatus(HttpStatus.NO_CONTENT)
    fun deleteTask(request: HttpServletRequest, @PathVariable caseId: Long, @PathVariable taskId: Long) {
        if (executed("delete_task", request, caseId, mapOf("task_id" to taskId)) != true) throw ApiFailure(404, "실행 작업이 없습니다")
    }
}
