package kr.propertyconcierge.core.store

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import com.fasterxml.jackson.databind.node.ObjectNode
import kr.propertyconcierge.core.ApiFailure
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.stereotype.Service
import org.springframework.transaction.support.TransactionTemplate
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

data class TaskTemplate(val key: String, val phase: String, val title: String, val actor: String, val anchor: String,
    val offset: Long, val required: Boolean = true)

@Service
class ExecutionStore(private val jdbc: JdbcTemplate, private val json: ObjectMapper, private val tx: TransactionTemplate) {
    private fun now() = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"))
    private val templates = listOf(
        TaskTemplate("site_visit", "before_contract", "현장 방문 및 하자 확인", "self", "contract", -7),
        TaskTemplate("appraisal_review", "before_contract", "시세분석 확인", "self", "contract", -7),
        TaskTemplate("rights_check", "before_contract", "최신 등기부·건축물대장 확인", "self", "contract", -1),
        TaskTemplate("funding_check", "before_contract", "대출 가능 금액 확인", "bank", "contract", -7),
        TaskTemplate("extra_costs", "before_contract", "취득세·중개보수 등 부대비용 확인", "self", "contract", -5),
        TaskTemplate("broker_explanation", "before_contract", "중개대상물 확인설명서 검토", "broker", "contract", -1),
        TaskTemplate("contract_review", "before_contract", "계약서·특약 초안 검토", "self", "contract", -3),
        TaskTemplate("loan_approval", "before_closing", "대출 본심사 완료 확인", "bank", "closing", -14),
        TaskTemplate("closing_funds", "before_closing", "잔금 자금 확보", "self", "closing", -7),
        TaskTemplate("management_fees", "before_closing", "체납 관리비 확인", "broker", "closing", -1),
        TaskTemplate("fixtures", "before_closing", "시설물 인수 목록 확인", "self", "closing", -3, false),
        TaskTemplate("registration_schedule", "before_closing", "법무사 등기 일정 확인", "legal_agent", "closing", -7),
        TaskTemplate("final_registry", "closing_day", "잔금 지급 전 권리변동 재확인", "legal_agent", "closing", 0),
        TaskTemplate("closing_payment", "closing_day", "잔금 지급", "self", "closing", 0),
        TaskTemplate("handover", "closing_day", "열쇠·시설물 인수", "self", "closing", 0),
        TaskTemplate("registration_filing", "closing_day", "소유권이전등기 접수 확인", "legal_agent", "closing", 0),
        TaskTemplate("acquisition_tax", "after_closing", "취득세 신고·납부 확인", "tax_agent", "closing", 30),
        TaskTemplate("registration_complete", "after_closing", "소유권이전등기 완료 확인", "legal_agent", "closing", 30))
    private fun row(sql: String, vararg params: Any?): ObjectNode? = jdbc.queryForList(sql, *params).firstOrNull()?.let { json.valueToTree(it) }
    private fun due(template: TaskTemplate, plan: JsonNode): String? {
        val date = plan.get(if (template.anchor == "contract") "contract_planned_date" else "closing_planned_date")?.takeUnless(JsonNode::isNull)?.asText()
        return date?.let { dateValue(it).plusDays(template.offset).toString() }
    }
    private fun dateValue(text: String): LocalDate = try { LocalDate.parse(text) }
        catch (error: java.time.DateTimeException) { throw ApiFailure(422, "유효한 날짜를 입력해주세요") }

    private fun syncAnalysisEvidence(plan: JsonNode) {
        val propertyId = plan.path("property_id").asLong()
        for (analysis in jdbc.queryForList("SELECT * FROM candidate_analyses WHERE property_id=?", propertyId)) {
            val type = analysis["analysis_type"].toString()
            val key = mapOf("appraisal" to "appraisal_review", "rights" to "rights_check", "simulation" to "funding_check")[type] ?: continue
            val task = row("SELECT * FROM case_execution_tasks WHERE plan_id=? AND template_key=?", plan.path("id").asLong(), key) ?: continue
            val timestamp = analysis["expires_at"]?.toString()
            val fresh = analysis["status"] == "completed" && timestamp != null && try {
                LocalDateTime.parse(timestamp.replace(' ', 'T')) >= LocalDateTime.now()
            } catch (error: java.time.DateTimeException) { false }
            val checked = task.path("checked_by").asText()
            val taskId = task.path("id").asLong()
            if (type == "simulation") {
                val note = task.path("evidence_note").asText()
                if (note.isBlank() || note.startsWith("자금 시뮬레이션")) jdbc.update(
                    "UPDATE case_execution_tasks SET evidence_note=? WHERE id=?",
                    if (fresh) "자금 시뮬레이션 결과 연결됨 — 은행 승인과는 다름" else "자금 시뮬레이션 갱신 필요", taskId)
            } else if (fresh && checked in setOf("", "시스템")) {
                val facts = json.readTree(analysis["summary"].toString())
                val status = if (type == "appraisal" || facts.path("risk_grade").asText() == "safe") "done" else "problem"
                val outcome = if (type == "appraisal") "유효한 시세분석 결과가 연결됨" else
                    "문서 기반 권리분석 결과: ${facts.get("risk_label")?.takeUnless(JsonNode::isNull)?.asText() ?: facts.path("risk_grade").asText()}"
                jdbc.update("UPDATE case_execution_tasks SET status=?,checked_by='시스템',outcome=?,completed_at=? WHERE id=?", status, outcome, now(), taskId)
            } else if (!fresh && analysis["status"] in setOf("completed", "stale") && checked == "시스템") {
                jdbc.update("UPDATE case_execution_tasks SET status='scheduled',checked_by='',completed_at=null,outcome=? WHERE id=?",
                    if (type == "appraisal") "시세분석 유효기간 만료 — 갱신 필요" else "권리분석 유효기간 만료 — 최신 문서 재확인 필요", taskId)
            }
        }
    }
    fun ensure(caseId: Long, propertyId: Long): ObjectNode {
        var plan = row("SELECT * FROM case_execution_plans WHERE case_id=?", caseId)
        if (plan == null) {
            val id = jdbc.queryForObject("INSERT INTO case_execution_plans(case_id,property_id,status,created,updated) VALUES (?,?,'preparing',?,?) RETURNING id", Long::class.java, caseId, propertyId, now(), now())
            plan = requireNotNull(row("SELECT * FROM case_execution_plans WHERE id=?", id))
        } else if (plan.path("property_id").asLong() != propertyId) {
            val id = plan.path("id").asLong()
            jdbc.update("UPDATE case_execution_plans SET property_id=?,contract_planned_date=null,closing_planned_date=null,updated=? WHERE id=?", propertyId, now(), id)
            jdbc.update("DELETE FROM case_execution_tasks WHERE plan_id=? AND source='system'", id)
            jdbc.update("""UPDATE case_execution_tasks SET property_id=?,evidence_note=concat('이전 후보 #',property_id,' 기록: ',checked_by,' / ',outcome,' / ',evidence_note,' / ',follow_up),
                status='scheduled',checked_by='',outcome='',follow_up='',completed_at=null,due_date=null,updated=? WHERE plan_id=? AND source='user'""", propertyId, now(), id)
            plan = requireNotNull(row("SELECT * FROM case_execution_plans WHERE id=?", id))
        }
        val id = plan.path("id").asLong()
        templates.forEachIndexed { index, task ->
            jdbc.update("""INSERT INTO case_execution_tasks(plan_id,case_id,property_id,template_key,phase,title,description,actor_type,status,
                required,due_date,checked_by,outcome,evidence_note,follow_up,source,sort_order,created,updated)
                VALUES (?,?,?,?,?,?,'',?,'scheduled',?,?,'','','','','system',?,?,?) ON CONFLICT(plan_id,template_key) DO NOTHING""",
                id, caseId, propertyId, task.key, task.phase, task.title, task.actor, task.required, due(task, plan), index, now(), now())
        }
        return plan
    }
    fun reset(caseId: Long) {
        jdbc.update("UPDATE case_execution_plans SET contract_planned_date=null,closing_planned_date=null,updated=? WHERE case_id=?", now(), caseId)
        jdbc.update("""UPDATE case_execution_tasks SET status='scheduled',completed_at=null,due_date=null,checked_by='',outcome='',follow_up='',
            evidence_note='원본 매물 변경 전 확인 기록은 변경 이력에 보관됨',updated=? WHERE case_id=?""", now(), caseId)
    }
    private fun taskView(task: ObjectNode): ObjectNode = task.apply {
        val date = get("due_date")?.takeUnless(JsonNode::isNull)?.asText()
        put("overdue", date != null && LocalDate.parse(date) < LocalDate.now() && path("status").asText() !in setOf("done", "not_applicable"))
        remove(listOf("case_id", "property_id"))
    }
    private fun summary(tasks: List<JsonNode>): Map<String, Any> {
        val done = tasks.filter { it.path("status").asText() in setOf("done", "not_applicable") }
        val problems = tasks.filter { it.path("status").asText() == "problem" }
        val overdue = tasks.filter { it.path("overdue").asBoolean() }
        fun weight(items: List<JsonNode>) = items.sumOf { if (it.path("required").asBoolean()) 2 else 1 }
        return mapOf("progress_percent" to if (weight(tasks) == 0) 0 else Math.rint(weight(done).toDouble()/weight(tasks)*100).toInt(),
            "total" to tasks.size, "done" to done.size, "overdue" to overdue.size, "problems" to problems.size,
            "waiting_external" to tasks.count { it.path("status").asText() == "waiting_external" },
            "blockers" to problems.map { mapOf("task_id" to it.path("id").asLong(), "title" to it.path("title").asText(), "reason" to "문제 발견") } +
                overdue.filter { it !in problems }.map { mapOf("task_id" to it.path("id").asLong(), "title" to it.path("title").asText(), "reason" to "권장일 경과") })
    }
    private fun view(caseId: Long, plan: JsonNode?): Map<String, Any?> {
        val tasks = if (plan == null) emptyList() else jdbc.queryForList("SELECT * FROM case_execution_tasks WHERE plan_id=? ORDER BY sort_order,id", plan.path("id").asLong())
            .map { taskView(json.valueToTree(it)) }
        val info = (plan as? ObjectNode)?.deepCopy()?.apply { remove("case_id") }
        return mapOf("case_id" to caseId, "requires_selection" to (plan == null), "plan" to info, "tasks" to tasks, "summary" to summary(tasks))
    }
    fun dispatch(operation: String, args: JsonNode): Any? = tx.execute<Any?> {
        val owner = args.path("user_id").asLong(); val caseId = args.path("case_id").asLong()
        val case = row("SELECT * FROM purchase_cases WHERE id=? AND user_id=? FOR UPDATE", caseId, owner) ?: return@execute null
        val property = case.get("selected_property_id")?.takeUnless(JsonNode::isNull)?.asLong()
        if (property == null) return@execute if (operation == "get_execution") view(caseId, null) else null
        if (operation == "ensure_execution_plan" && args.path("property_id").asLong() != property) return@execute null
        val plan = ensure(caseId, property); val planId = plan.path("id").asLong(); val data = args.path("data")
        if (operation == "get_execution") syncAnalysisEvidence(plan)
        val result = when (operation) {
            "get_execution", "ensure_execution_plan" -> view(caseId, plan)
            "update_plan" -> {
                val contract = if (data.has("contract_planned_date")) data.get("contract_planned_date")?.takeUnless(JsonNode::isNull)?.asText() else plan.get("contract_planned_date")?.takeUnless(JsonNode::isNull)?.asText()
                val closing = if (data.has("closing_planned_date")) data.get("closing_planned_date")?.takeUnless(JsonNode::isNull)?.asText() else plan.get("closing_planned_date")?.takeUnless(JsonNode::isNull)?.asText()
                val contractValue = contract?.let(::dateValue); val closingValue = closing?.let(::dateValue)
                if (contractValue != null && closingValue != null && contractValue > closingValue) throw ApiFailure(422, "잔금 예정일은 계약 예정일보다 빠를 수 없습니다")
                jdbc.update("UPDATE case_execution_plans SET contract_planned_date=?,closing_planned_date=?,updated=? WHERE id=?", contract, closing, now(), planId)
                val updated = requireNotNull(row("SELECT * FROM case_execution_plans WHERE id=?", planId))
                templates.forEach { task -> jdbc.update("UPDATE case_execution_tasks SET due_date=?,updated=? WHERE plan_id=? AND template_key=? AND status NOT IN ('done','not_applicable')", due(task, updated), now(), planId, task.key) }
                view(caseId, updated)
            }
            "add_task" -> {
                data.get("due_date")?.takeUnless(JsonNode::isNull)?.asText()?.let(::dateValue)
                val order = (jdbc.queryForObject("SELECT coalesce(max(sort_order),0) FROM case_execution_tasks WHERE plan_id=?", Int::class.java, planId) ?: 0) + 1
                val id = jdbc.queryForObject("""INSERT INTO case_execution_tasks(plan_id,case_id,property_id,phase,title,description,actor_type,status,
                    required,due_date,checked_by,outcome,evidence_note,follow_up,source,sort_order,created,updated)
                    VALUES (?,?,?,?,?,?,?,'scheduled',?,?,'','','','','user',?,?,?) RETURNING id""", Long::class.java, planId, caseId, property,
                    data.path("phase").asText(), data.path("title").asText(), data.path("description").asText(""), data.path("actor_type").asText("self"),
                    data.path("required").asBoolean(), data.get("due_date")?.takeUnless(JsonNode::isNull)?.asText(), order, now(), now())
                taskView(requireNotNull(row("SELECT * FROM case_execution_tasks WHERE id=?", id)))
            }
            "update_task", "delete_task" -> {
                val task = row("SELECT * FROM case_execution_tasks WHERE id=? AND case_id=? AND plan_id=?", args.path("task_id").asLong(), caseId, planId) ?: return@execute null
                val id = task.path("id").asLong()
                if (operation == "delete_task") {
                    if (task.path("source").asText() != "user") throw ApiFailure(422, "시스템 기본 작업은 삭제할 수 없습니다. 해당 없음으로 변경해주세요")
                    jdbc.update("DELETE FROM case_execution_tasks WHERE id=?", id) > 0
                } else {
                    data.get("due_date")?.takeUnless(JsonNode::isNull)?.asText()?.let(::dateValue)
                    val status = data.get("status")?.takeUnless(JsonNode::isNull)?.asText() ?: task.path("status").asText()
                    val checked = data.get("checked_by")?.takeUnless(JsonNode::isNull)?.asText() ?: task.path("checked_by").asText()
                    val outcome = data.get("outcome")?.takeUnless(JsonNode::isNull)?.asText() ?: task.path("outcome").asText()
                    if (status in setOf("done", "problem") && (checked.isBlank() || outcome.isBlank())) throw ApiFailure(422, "실제 확인자와 확인 결과가 필요합니다")
                    val fields = setOf("status", "actor_type", "due_date", "checked_by", "outcome", "evidence_note", "follow_up")
                    data.fields().forEach { (key, value) ->
                        if (key !in fields) throw ApiFailure(422, "변경할 수 없는 실행 작업 필드입니다")
                        jdbc.update("UPDATE case_execution_tasks SET $key=? WHERE id=?", value.takeUnless(JsonNode::isNull)?.asText(), id)
                    }
                    jdbc.update("UPDATE case_execution_tasks SET completed_at=?,updated=? WHERE id=?", if (status in setOf("done", "problem", "not_applicable")) now() else null, now(), id)
                    taskView(requireNotNull(row("SELECT * FROM case_execution_tasks WHERE id=?", id)))
                }
            }
            else -> throw ApiFailure(404, "실행 작업 경로가 없습니다")
        }
        if (operation != "get_execution") jdbc.update("UPDATE purchase_cases SET updated=? WHERE id=?", now(), caseId)
        result
    }
}
