package kr.propertyconcierge.core.store

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import com.fasterxml.jackson.databind.node.ObjectNode
import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.bridge.PythonClient
import kr.propertyconcierge.core.listings.ListingService
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.stereotype.Service
import org.springframework.transaction.support.TransactionTemplate
import org.springframework.transaction.TransactionDefinition
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

@Service
class CaseStore(private val jdbc: JdbcTemplate, private val json: ObjectMapper, private val tx: TransactionTemplate,
    private val listings: ListingService, private val python: PythonClient, private val execution: ExecutionStore) {
    private fun limitedValuation(summary: JsonNode): Boolean =
        summary.path("result_kind").asText() in setOf("conditional_scenario", "public_reference", "partial_reference", "withheld", "unsupported") ||
            (summary.hasNonNull("valuation") && !summary.path("valuation").path("comparison_eligible").asBoolean(false))
    private val jsonFields = setOf("buyer_profile", "target_regions", "source_snapshot", "summary", "stats_snapshot", "result",
        "previous_snapshot", "applied_snapshot", "previous_decision", "invalidated_analyses", "previous_analyses", "previous_execution")
    private val snapshotTransaction = TransactionTemplate(requireNotNull(tx.transactionManager)).apply {
        isReadOnly = true
        isolationLevel = TransactionDefinition.ISOLATION_REPEATABLE_READ
        propagationBehavior = TransactionDefinition.PROPAGATION_REQUIRES_NEW
    }
    fun now() = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"))
    private fun version() = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss.SSSSSS"))
    private fun JsonNode.id(name: String): Long = path(name).takeIf { it.isIntegralNumber && it.canConvertToLong() && it.asLong() > 0 }?.asLong()
        ?: throw ApiFailure(422, "식별자를 확인해주세요")
    private fun JsonNode.text(name: String, fallback: String = "") = get(name)?.takeUnless(JsonNode::isNull)?.asText() ?: fallback
    private fun JsonNode.amount(name: String): Long? = get(name)?.takeUnless(JsonNode::isNull)?.let {
        if (!it.isIntegralNumber || !it.canConvertToLong() || it.asLong() < 0) throw ApiFailure(422, "금액은 원 단위 양수 정수로 입력해주세요")
        it.asLong()
    }
    fun objectRow(row: Map<String, Any?>): ObjectNode = json.createObjectNode().also { result ->
        row.forEach { (key, value) -> result.set<JsonNode>(key,
            if (key in jsonFields && value != null) json.readTree(value.toString()) else json.valueToTree(value)) }
    }
    private fun one(sql: String, vararg args: Any?): ObjectNode? = jdbc.queryForList(sql, *args).firstOrNull()?.let(::objectRow)
    fun owned(owner: Long, caseId: Long, lock: Boolean = false): ObjectNode? = one(
        "SELECT * FROM purchase_cases WHERE id=? AND user_id=?" + if (lock) " FOR UPDATE" else "", caseId, owner)
    private fun candidate(caseId: Long, propertyId: Long): ObjectNode? = one("SELECT * FROM case_properties WHERE case_id=? AND id=?", caseId, propertyId)
    private fun base(case: ObjectNode): ObjectNode = case.deepCopy().apply {
        remove("user_id"); put("property_count", jdbc.queryForObject("SELECT count(*) FROM case_properties WHERE case_id=?", Int::class.java, case.path("id").asLong()) ?: 0)
    }
    private fun touch(caseId: Long) { jdbc.update("UPDATE purchase_cases SET updated=? WHERE id=?", now(), caseId) }
    // HTTP로 왕복하면 IntNode·LongNode가 달라진다. 값이 같은 금액을 입력 변경으로 오인하지 않는다.
    private fun same(left: JsonNode?, right: JsonNode?): Boolean {
        if (left == null || right == null) return left == right
        if (left.isNumber && right.isNumber) return left.decimalValue().compareTo(right.decimalValue()) == 0
        if (left.isObject && right.isObject) return left.fieldNames().asSequence().toSet() == right.fieldNames().asSequence().toSet() &&
            left.fieldNames().asSequence().all { same(left.get(it), right.get(it)) }
        if (left.isArray && right.isArray) return left.size() == right.size() && (0 until left.size()).all { same(left[it], right[it]) }
        return left == right
    }
    private fun identity(value: JsonNode): JsonNode {
        val input = value.path("identity").takeIf(JsonNode::isObject) ?: value
        val unit = input.text("unit_number").trim()
        val fields = listOf("building_dong", "unit_number", "floor").associateWith { input.text(it).trim() }
        val basis = input.text("area_basis", "unknown")
        if (fields.values.any { it.length > 30 || it.any(Char::isISOControl) } || basis !in setOf("exclusive", "supply", "unknown"))
            throw ApiFailure(422, "동·호·층·면적 기준의 입력을 확인해주세요")
        return json.valueToTree(fields + mapOf("area_basis" to basis, "unit_source" to if (unit.isBlank()) "unknown" else "user_input",
            "verification_level" to if (unit.isBlank()) "building_or_parcel" else "unit_user_input"))
    }
    private fun rows(sql: String, vararg args: Any?) = jdbc.queryForList(sql, *args).map(::objectRow)
    private fun sourceStatus(owner: Long, property: JsonNode): JsonNode? {
        val id = property.get("source_listing_id")?.takeUnless(JsonNode::isNull)?.asLong() ?: return null
        val saved = property.path("source_snapshot")
        val current = try { listings.get(owner, id) } catch (error: ApiFailure) {
            if (error.status != 404) throw error
            return json.valueToTree(mapOf("status" to "missing", "listing_id" to id, "changes" to emptyMap<String, Any>(),
                "needs_confirmation" to true, "saved" to saved, "current" to null))
        }
        val fields = listOf("name", "asking_price", "address", "area_sqm", "status", "legal_region_code", "property_type", "identity")
        (current as ObjectNode).set<JsonNode>("identity", identity(current))
        val savedIdentity = identity(saved)
        val changes = fields.filter { !same(if (it == "identity") savedIdentity else saved.path(it), current.path(it)) }.associateWith { mapOf("saved" to saved.get(it), "current" to current.get(it)) }
        val needs = current.path("needs_confirmation").asBoolean() || current.path("status").asText() != "active"
        val facts = json.createObjectNode(); fields.forEach { facts.set<JsonNode>(it, current.get(it)) }
        facts.set<JsonNode>("revision_id", json.valueToTree(jdbc.queryForObject("SELECT max(id) FROM listing_revisions WHERE listing_id=?", Long::class.java, id)))
        facts.set<JsonNode>("confirmed_at", current.get("confirmed_at")); facts.set<JsonNode>("last_collection_outcome", current.get("last_collection_outcome"))
        return json.valueToTree(mapOf("status" to if (changes.isNotEmpty()) "changed" else if (needs) "needs_confirmation" else "current",
            "listing_id" to id, "changes" to changes, "needs_confirmation" to needs, "saved" to saved, "current" to facts))
    }
    fun snapshot(owner: Long, caseId: Long): JsonNode? {
        // 개별 조회 사이의 변경으로 예산·후보·분석이 다른 시점의 상태가 되지 않도록 한다.
        val aggregate = snapshotTransaction.execute {
            val case = owned(owner, caseId) ?: return@execute null
            val properties = rows("SELECT * FROM case_properties WHERE case_id=? ORDER BY created,id", caseId)
            val history = rows("SELECT * FROM history WHERE user_id=? AND id IN (SELECT history_id FROM case_properties WHERE case_id=?)", owner, caseId)
                .associateBy { it.path("id").asText() }
            mapOf("case" to case, "properties" to properties.map { property ->
                val id = property.path("id").asLong()
                mapOf("property" to property, "source_status" to sourceStatus(owner, property),
                    "analyses" to rows("SELECT * FROM candidate_analyses WHERE property_id=?", id),
                    "checklist" to rows("SELECT * FROM candidate_checklist_items WHERE property_id=? ORDER BY sort_order,id", id),
                    "source_reviews" to rows("SELECT * FROM candidate_source_reviews WHERE property_id=? AND user_id=? ORDER BY id DESC", id, owner))
            }, "histories" to history, "regions" to rows("SELECT * FROM case_regions WHERE case_id=? ORDER BY created,id", caseId))
        } ?: return null
        // DB 연결을 반환한 뒤 원격 분석한다. 느린 AI가 트랜잭션을 점유하지 않게 한다.
        return python.analyze("decision/decorate", mapOf("snapshot" to aggregate))
    }
    private fun snapshotFields(source: JsonNode, id: Long): ObjectNode = json.createObjectNode().apply {
        for (field in listOf("name", "alias", "address_details", "asking_price", "address", "area_sqm", "status", "legal_region_code", "property_type", "confirmed_at"))
            set<JsonNode>(field, source.get(field))
        put("listing_id", id); set<JsonNode>("revision_id", json.valueToTree(jdbc.queryForObject("SELECT max(id) FROM listing_revisions WHERE listing_id=?", Long::class.java, id)))
        set<JsonNode>("identity", identity(source))
    }
    private fun checkedSource(owner: Long, id: Long): ObjectNode {
        if (one("SELECT id FROM imported_listings WHERE user_id=? AND id=? FOR UPDATE", owner, id) == null)
            throw ApiFailure(404, "매물을 찾을 수 없습니다")
        val source = listings.get(owner, id)
        if (source.path("transaction_type").asText() != "purchase") throw ApiFailure(422, "매매 매물만 매수 후보로 저장할 수 있습니다")
        if (source.path("status").asText() != "active" || source.path("needs_confirmation").asBoolean() || !source.path("region_linked").asBoolean())
            throw ApiFailure(409, "법정동 연결 및 최근 7일 이내 거래 가능 상태를 확인해주세요")
        return source
    }
    private fun patch(table: String, id: Long, data: JsonNode, allowed: Set<String>, extra: Map<String, Any?> = emptyMap()) {
        val values = mutableListOf<Any?>(); val assignments = mutableListOf<String>()
        data.fields().forEach { (key, value) ->
            if (key !in allowed) throw ApiFailure(422, "변경할 수 없는 필드입니다")
            assignments.add("$key=?" + if (key in jsonFields) "::json" else "")
            values.add(if (key in jsonFields) json.writeValueAsString(value) else when {
                value.isNull -> null; value.isIntegralNumber -> value.asLong(); value.isNumber -> value.asDouble()
                value.isBoolean -> value.asBoolean(); else -> value.asText()
            })
        }
        extra.forEach { (key, value) -> assignments.add("$key=?"); values.add(value) }
        if (assignments.isNotEmpty()) jdbc.update("UPDATE $table SET ${assignments.joinToString(",")} WHERE id=?", *(values + id).toTypedArray())
    }
    fun dispatch(operation: String, args: JsonNode): Any? {
        val owner = args.id("user_id")
        val caseId = if (operation in setOf("create_case", "list_cases")) null else args.id("case_id")
        if (operation == "get_case") return snapshot(owner, requireNotNull(caseId))
        if (operation == "list_cases") return rows("SELECT * FROM purchase_cases WHERE user_id=? ORDER BY updated DESC,id DESC", owner).map(::base)
        if (operation == "candidate_inputs" || operation == "validate_candidate") {
            val property = if (owned(owner, requireNotNull(caseId)) != null) candidate(caseId, args.id("property_id")) else null
            return if (operation == "validate_candidate") property != null else property?.let(::inputs)
        }
        val historyId = when (operation) {
            "link_appraisal" -> args.id("history_id")
            "add_property" -> args.path("data").get("history_id")?.takeUnless(JsonNode::isNull)?.asLong()
            else -> null
        }
        val history = historyId?.let { one("SELECT * FROM history WHERE id=? AND user_id=?", it, owner)
            ?: throw ApiFailure(404, "시세추정 이력을 찾을 수 없습니다") }
        // 원격 분석은 트랜잭션 밖에서 수행하고, 저장 시 소유자와 후보 입력을 다시 검사한다.
        val appraisalSummary = historyId?.let { python.analyze("appraisal/summary", mapOf("history_id" to it,
            "result" to if (operation == "link_appraisal") args.path("result") else requireNotNull(history).path("result"))) }
        val result = tx.execute<Any?> {
            val case = caseId?.let { owned(owner, it, true) }
            if (caseId != null && case == null) return@execute null
            val data = args.path("data")
            when (operation) {
                "create_case" -> {
                    val id = jdbc.queryForObject("""INSERT INTO purchase_cases(user_id,title,status,purpose,budget_min,budget_max,buyer_profile,
                        target_regions,notes,decision_reason,created,updated) VALUES (?,?,'exploring','purchase',?,?,?::json,?::json,?,'',?,?) RETURNING id""",
                        Long::class.java, owner, data.text("title"), data.amount("budget_min"), data.amount("budget_max"),
                        data.path("buyer_profile").toString(), data.path("target_regions").toString(), data.text("notes"), now(), now())
                    base(requireNotNull(owned(owner, requireNotNull(id))))
                }
                "update_case" -> {
                    val current = requireNotNull(case)
                    val minimum = if (data.has("budget_min")) data.amount("budget_min") else current.amount("budget_min")
                    val maximum = if (data.has("budget_max")) data.amount("budget_max") else current.amount("budget_max")
                    if (minimum != null && maximum != null && minimum > maximum)
                        throw ApiFailure(422, "최소 예산은 최대 예산보다 클 수 없습니다")
                    patch("purchase_cases", requireNotNull(caseId), data, setOf("title", "status", "budget_min", "budget_max", "buyer_profile", "target_regions", "notes"), mapOf("updated" to now()))
                    base(requireNotNull(owned(owner, caseId)))
                }
                "delete_case" -> jdbc.update("DELETE FROM purchase_cases WHERE id=? AND user_id=?", caseId, owner) > 0
                "add_property" -> {
                    if (data.text("status") == "selected") throw ApiFailure(422, "후보 추가 후 선택 근거와 함께 최종 선택해주세요")
                    val sourceId = data.get("source_listing_id")?.takeUnless(JsonNode::isNull)?.asLong()
                    val source = sourceId?.let { checkedSource(owner, it) }
                    val existing = sourceId?.let { one("SELECT * FROM case_properties WHERE case_id=? AND source_listing_id=?", caseId, it) }
                    if (existing != null) return@execute mapOf("property_id" to existing.path("id").asLong(), "already" to true)
                    val historyId = data.get("history_id")?.takeUnless(JsonNode::isNull)?.asLong()
                    if (historyId != null && one("SELECT id FROM history WHERE id=? AND user_id=?", historyId, owner) == null)
                        throw ApiFailure(404, "시세추정 이력을 찾을 수 없습니다")
                    val snapshot = if (source != null) snapshotFields(source, requireNotNull(sourceId)) else json.createObjectNode()
                    if (source == null) snapshot.set<JsonNode>("identity", identity(data))
                    val id = requireNotNull(jdbc.queryForObject("""INSERT INTO case_properties(case_id,name,address,category,asking_price,area_sqm,
                        legal_region_code,source,status,notes,history_id,source_listing_id,source_snapshot,created,updated)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?::json,?,?) RETURNING id""", Long::class.java, caseId,
                        source?.text("name") ?: data.text("name"), source?.text("address") ?: data.text("address"),
                        source?.text("property_type") ?: data.text("category"), source?.amount("asking_price") ?: data.amount("asking_price"),
                        (source ?: data).get("area_sqm")?.takeUnless(JsonNode::isNull)?.asDouble(),
                        (source ?: data).get("legal_region_code")?.takeUnless(JsonNode::isNull)?.asText(), data.text("source", "manual"),
                        data.text("status", "reviewing"), if (source == null) data.text("notes") else
                            "제공 매물 #$sourceId · 출처 ${source.text("source_name")} / ${source.text("external_id")} · 확인 ${source.text("confirmed_at")}\n" +
                            "원문 ${source.text("source_url", "없음")} · 사용자 제공 정보이며 서비스가 독립 확인한 것은 아닙니다.",
                        historyId, sourceId, snapshot.toString(), now(), version()))
                    listOf("price" to "적정가격 확인", "funding" to "자금 조건 입력 필요", "rights" to "권리서류 업로드 필요", "site" to "현장 상태 확인", "contract" to "계약 조건 확인")
                        .forEachIndexed { index, (category, title) -> jdbc.update("""INSERT INTO candidate_checklist_items(case_id,property_id,category,title,status,
                            source,evidence,sort_order,created,updated) VALUES (?,?,?,?,'todo','system','',?,?,?)""", caseId, id, category, title, index, now(), now()) }
                    if (historyId != null) {
                        val timestamp = requireNotNull(history).text("created")
                        jdbc.update("""INSERT INTO candidate_analyses(case_id,property_id,analysis_type,reference_id,status,summary,analyzed_at,
                            expires_at,created,updated) VALUES (?,?,'appraisal',?,'completed',?::json,?,?,?,?)""", caseId, id, historyId,
                            requireNotNull(appraisalSummary).toString(), timestamp,
                            LocalDateTime.parse(timestamp.replace(' ', 'T')).plusDays(30).format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")), now(), now())
                        val limited = limitedValuation(appraisalSummary)
                        jdbc.update("""UPDATE candidate_checklist_items SET status=?,source='appraisal',evidence=?,completed_at=?
                            WHERE property_id=? AND category='price'""", if (limited) "todo" else "done",
                            if (limited) "참고자료 이력 #$historyId 연결 · 시장가격 확인 필요" else "시세추정 이력 #$historyId 연결", if (limited) null else now(), id)
                    }
                    touch(requireNotNull(caseId)); mapOf("property_id" to id, "already" to false)
                }
                "update_property" -> {
                    val propertyId = args.id("property_id"); val item = candidate(requireNotNull(caseId), propertyId) ?: return@execute null
                    val selected = case?.path("selected_property_id")?.asLong() == propertyId
                    if ((data.text("status") == "selected" && !selected) || (selected && data.has("status") && data.text("status") != "selected"))
                        throw ApiFailure(422, "최종 선택은 후보 검토 화면에서 선택 근거와 함께 변경해주세요")
                    if (data.has("identity")) {
                        if (item.hasNonNull("source_listing_id")) throw ApiFailure(422, "등록 매물의 동·호 정보는 원본을 갱신한 뒤 재검토해주세요")
                        val before = item.path("source_snapshot").takeIf(JsonNode::isObject)?.deepCopy<ObjectNode>() ?: json.createObjectNode()
                        val after = identity(data)
                        if (!same(identity(before), after)) {
                            if (data.text("status") == "selected") throw ApiFailure(422, "물건 정보를 바꾼 뒤 다시 검토·선택해주세요")
                            val afterSnapshot = before.deepCopy().apply { set<JsonNode>("identity", after) }
                            val previousAnalyses = rows("SELECT analysis_type AS type,status,summary,analyzed_at,reference_id FROM candidate_analyses WHERE property_id=?", propertyId)
                            val previousTasks = if (selected) rows("SELECT id,title,status,checked_by,outcome,evidence_note FROM case_execution_tasks WHERE case_id=?", caseId) else emptyList()
                            val decision = if (selected) json.writeValueAsString(mapOf("property_id" to propertyId, "reason" to case?.get("decision_reason"), "decided_at" to case?.get("decided_at"))) else null
                            jdbc.update("""INSERT INTO candidate_source_reviews(case_id,property_id,user_id,previous_snapshot,applied_snapshot,previous_decision,
                                invalidated_analyses,previous_analyses,previous_execution,created) VALUES (?,?,?,?::json,?::json,?::json,?::json,?::json,?::json,?)""",
                                caseId, propertyId, owner, before.toString(), afterSnapshot.toString(), decision,
                                json.writeValueAsString(listOf("appraisal", "rights", "simulation")), json.writeValueAsString(previousAnalyses), json.writeValueAsString(previousTasks), now())
                            jdbc.update("UPDATE case_properties SET source_snapshot=?::json WHERE id=?", afterSnapshot.toString(), propertyId)
                            jdbc.update("UPDATE candidate_analyses SET status='stale',updated=? WHERE property_id=?", now(), propertyId)
                            jdbc.update("UPDATE candidate_checklist_items SET status='todo',completed_at=null WHERE property_id=? AND category IN ('price','funding','rights')", propertyId)
                            if (selected) {
                                execution.reset(caseId)
                                jdbc.update("UPDATE purchase_cases SET selected_property_id=null,decided_at=null,decision_reason='',status='reviewing' WHERE id=?", caseId)
                                jdbc.update("UPDATE case_properties SET status='shortlisted' WHERE id=?", propertyId)
                            }
                        }
                    }
                    val fields = data.deepCopy<ObjectNode>().apply { remove("identity") }
                    patch("case_properties", item.path("id").asLong(), fields, setOf("asking_price", "status", "notes"), mapOf("updated" to version()))
                    touch(caseId); mapOf("property_id" to propertyId)
                }
                "delete_property" -> {
                    val propertyId = args.id("property_id")
                    if (case?.path("selected_property_id")?.asLong() == propertyId) throw ApiFailure(422, "최종 선택된 후보는 삭제할 수 없습니다")
                    val deleted = jdbc.update("DELETE FROM case_properties WHERE id=? AND case_id=?", propertyId, caseId) > 0
                    if (deleted) touch(requireNotNull(caseId)); deleted
                }
                "update_checklist" -> {
                    val check = one("SELECT * FROM candidate_checklist_items WHERE id=? AND property_id=? AND case_id=?", args.id("checklist_id"), args.id("property_id"), caseId) ?: return@execute null
                    patch("candidate_checklist_items", check.path("id").asLong(), data, setOf("status", "evidence"),
                        mapOf("completed_at" to if (data.text("status") == "done") now() else null, "updated" to now()))
                    touch(requireNotNull(caseId)); one("SELECT * FROM candidate_checklist_items WHERE id=?", check.path("id").asLong())
                }
                "select_final_candidate" -> {
                    val propertyId = args.id("property_id"); val property = candidate(requireNotNull(caseId), propertyId) ?: return@execute null
                    val reason = args.text("reason").trim(); if (reason.length !in 3..5000) throw ApiFailure(422, "선택 근거를 3자 이상 입력해주세요")
                    val source = sourceStatus(owner, property)
                    if (source != null && source.path("status").asText() != "current") throw ApiFailure(422, "원본 매물 변경 또는 확인 만료를 먼저 검토해주세요")
                    if (source != null && jdbc.queryForObject("SELECT count(*) FROM candidate_analyses WHERE property_id=? AND status='stale'", Long::class.java, propertyId) != 0L)
                        throw ApiFailure(422, "원본 변경으로 무효화된 분석을 다시 확인해주세요")
                    jdbc.update("UPDATE case_properties SET status=CASE WHEN id=? THEN 'selected' WHEN status='selected' THEN 'shortlisted' ELSE status END,updated=? WHERE case_id=?", propertyId, version(), caseId)
                    jdbc.update("UPDATE purchase_cases SET selected_property_id=?,decision_reason=?,decided_at=?,status='decided',updated=? WHERE id=?", propertyId, reason, now(), now(), caseId)
                    execution.ensure(caseId, propertyId); base(requireNotNull(owned(owner, caseId)))
                }
                "clear_final_candidate" -> {
                    jdbc.update("UPDATE case_properties SET status='shortlisted',updated=? WHERE case_id=? AND status='selected'", version(), caseId)
                    jdbc.update("UPDATE purchase_cases SET selected_property_id=null,decision_reason='',decided_at=null,status='reviewing',updated=? WHERE id=?", now(), caseId)
                    base(requireNotNull(owned(owner, requireNotNull(caseId))))
                }
                "link_candidate_analysis", "link_appraisal" -> linkAnalysis(operation, args, requireNotNull(caseId), owner, appraisalSummary)
                "apply_listing_update" -> applySource(args, requireNotNull(caseId), owner, requireNotNull(case))
                "add_region" -> {
                    val code = data.text("region_code")
                    val region = one("SELECT * FROM legal_regions WHERE code=? AND is_active=true", code) ?: throw ApiFailure(404, "지역을 찾을 수 없습니다")
                    val existing = one("SELECT * FROM case_regions WHERE case_id=? AND region_code=?", caseId, code)
                    if (existing != null) existing else {
                        val id = jdbc.queryForObject("""INSERT INTO case_regions(case_id,region_code,region_name,source,property_type,budget_max_won,period_from,
                            period_to,stats_snapshot,created) VALUES (?,?,?,?,?,?,?,?,?::json,?) RETURNING id""", Long::class.java, caseId, code,
                            region.text("full_name"), data.text("source", "market_explorer"), data.text("property_type", "all"), data.amount("budget_max_won"),
                            data.text("period_from"), data.text("period_to"), data.path("stats_snapshot").toString(), now())
                        val regions = requireNotNull(case).path("target_regions").deepCopy<JsonNode>() as? com.fasterxml.jackson.databind.node.ArrayNode ?: json.createArrayNode()
                        if (regions.none { it.asText() == region.text("full_name") }) regions.add(region.text("full_name"))
                        jdbc.update("UPDATE purchase_cases SET target_regions=?::json,updated=? WHERE id=?", regions.toString(), now(), caseId)
                        one("SELECT * FROM case_regions WHERE id=?", id)
                    }
                }
                "delete_region" -> {
                    val region = one("SELECT * FROM case_regions WHERE id=? AND case_id=?", args.id("region_id"), caseId) ?: return@execute false
                    jdbc.update("DELETE FROM case_regions WHERE id=?", region.path("id").asLong())
                    val names = requireNotNull(case).path("target_regions").filter { it.asText() != region.text("region_name") }
                    jdbc.update("UPDATE purchase_cases SET target_regions=?::json,updated=? WHERE id=?", json.writeValueAsString(names), now(), caseId)
                    true
                }
                else -> throw ApiFailure(404, "이전되지 않은 저장 작업입니다")
            }
        }
        if (operation in setOf("add_property", "update_property") && result is Map<*, *>) {
            val property = snapshot(owner, requireNotNull(caseId))?.path("properties")?.firstOrNull { it.path("id").asLong() == result["property_id"] } as? ObjectNode
            if (result["already"] == true) property?.put("_already_linked", true)
            return property
        }
        return result
    }
    private fun inputs(property: JsonNode) = mapOf("address" to property.get("address"), "area_sqm" to property.get("area_sqm"),
        "category" to property.get("category"), "asking_price" to property.get("asking_price"), "source_revision_id" to property.path("source_snapshot").get("revision_id"),
        "identity" to identity(property.path("source_snapshot")))
    private fun linkAnalysis(operation: String, args: JsonNode, caseId: Long, owner: Long, appraisalSummary: JsonNode?): Boolean {
        val propertyId = args.id("property_id"); val item = candidate(caseId, propertyId) ?: return false
        val appraisal = operation == "link_appraisal"
        val type = if (appraisal) "appraisal" else args.text("analysis_type")
        val category = mapOf("appraisal" to "price", "simulation" to "funding", "rights" to "rights")[type] ?: throw ApiFailure(422, "지원하지 않는 분석 유형")
        val history = if (appraisal) args.id("history_id") else null
        if (history != null && one("SELECT id FROM history WHERE id=? AND user_id=?", history, owner) == null)
            throw ApiFailure(404, "시세추정 이력을 찾을 수 없습니다")
        if (args.hasNonNull("expected_inputs") && !same(json.valueToTree<JsonNode>(inputs(item)), args.path("expected_inputs"))) {
            if (appraisal && item.path("history_id").asLong() == history) return true
            throw ApiFailure(422, "분석 중 후보 정보가 바뀌었습니다. 최신 정보로 다시 실행해주세요")
        }
        val summary = if (appraisal) requireNotNull(appraisalSummary) else args.path("summary")
        if (appraisal && summary.hasNonNull("valuation")) {
            val subject = summary.path("valuation").path("subject")
            val addresses = setOf(item.text("address"), item.path("source_snapshot").path("address_details").path("jibun_address").asText(),
                item.path("source_snapshot").path("address_details").path("road_address").asText()).filter { it.isNotBlank() }
            if (subject.path("address").asText() !in addresses ||
                (subject.hasNonNull("area_sqm") && item.hasNonNull("area_sqm") && subject.path("area_sqm").decimalValue().compareTo(item.path("area_sqm").decimalValue()) != 0))
                throw ApiFailure(422, "평가 대상의 주소·면적이 후보와 다릅니다. 후보 정보를 먼저 수정해주세요")
            val subtype = mapOf("아파트" to "apartment", "오피스텔" to "officetel", "연립다세대" to "row_house",
                "상가" to "commercial", "사무실" to "office", "공장" to "factory", "창고" to "warehouse", "토지" to "land")
                .getOrDefault(item.text("category"), item.text("category"))
            if (subtype in setOf("apartment", "officetel", "row_house", "commercial", "office", "factory", "warehouse", "land") &&
                subject.path("subtype").asText() != subtype)
                throw ApiFailure(422, "평가 대상의 부동산 유형이 후보와 다릅니다")
            val unit = identity(item.path("source_snapshot"))
            if (mapOf("building_dong" to "dong", "unit_number" to "ho").any { (saved, analyzed) ->
                    unit.text(saved).isNotBlank() && unit.text(saved) != subject.path(analyzed).asText() })
                throw ApiFailure(422, "평가 대상의 동·호가 후보와 다릅니다")
        }
        // 공개 계산을 거치지 않는 내부 저장도 현재 후보 가격과 다른 결과를 연결하면 안 된다.
        // 가격 없는 과거 기록은 기존 호환성을 유지하고 의사결정 평가에서 미확인으로 구분한다.
        if (type == "simulation" && item.hasNonNull("asking_price") && summary.amount("purchase_price") != item.amount("asking_price"))
            throw ApiFailure(422, "후보의 현재 가격과 자금 분석 가격이 다릅니다. 최신 가격으로 다시 실행해주세요")
        val days = mapOf("appraisal" to 30L, "simulation" to 14L, "rights" to 7L).getValue(type)
        jdbc.update("""INSERT INTO candidate_analyses(case_id,property_id,analysis_type,reference_id,status,summary,analyzed_at,expires_at,created,updated)
            VALUES (?,?,?,?,'completed',?::json,?,?,?,?) ON CONFLICT(property_id,analysis_type) DO UPDATE SET reference_id=excluded.reference_id,
            status='completed',summary=excluded.summary,analyzed_at=excluded.analyzed_at,expires_at=excluded.expires_at,updated=excluded.updated""",
            caseId, propertyId, type, history, summary.toString(), now(), LocalDateTime.now().plusDays(days).format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")), now(), now())
        val limitedAppraisal = appraisal && limitedValuation(summary)
        val status = if (limitedAppraisal) "todo" else if (appraisal) "done" else args.text("checklist_status", "done")
        jdbc.update("UPDATE candidate_checklist_items SET status=?,source=?,evidence=?,completed_at=?,updated=? WHERE property_id=? AND category=?",
            status, type, if (limitedAppraisal) "참고자료 이력 #$history 연결 · 시장가격 확인 필요" else if (appraisal) "시세추정 이력 #$history 연결" else args.text("evidence"), if (status == "done") now() else null, now(), propertyId, category)
        if (appraisal) jdbc.update("UPDATE case_properties SET history_id=?,updated=? WHERE id=?", history, version(), propertyId)
        else jdbc.update("UPDATE case_properties SET updated=? WHERE id=?", version(), propertyId)
        touch(caseId); return true
    }
    private fun applySource(args: JsonNode, caseId: Long, owner: Long, case: ObjectNode): Any? {
        val propertyId = args.id("property_id"); val item = candidate(caseId, propertyId) ?: return null
        val sourceId = item.get("source_listing_id")?.takeUnless(JsonNode::isNull)?.asLong() ?: return null
        val source = checkedSource(owner, sourceId); val after = snapshotFields(source, sourceId); val before = item.path("source_snapshot")
        if (after.path("revision_id").asLong() != args.path("expected_revision_id").asLong() || source.text("confirmed_at") != args.text("expected_confirmed_at"))
            throw ApiFailure(422, "원본 매물이 다시 바뀌었습니다. 새 내용을 확인해주세요")
        val changed = listOf("name", "asking_price", "address", "area_sqm", "legal_region_code", "property_type", "status", "identity").filter {
            !same(if (it == "identity") identity(before) else before.path(it), after.path(it)) }
        if (changed.isEmpty() && before.path("confirmed_at") == after.path("confirmed_at"))
            return mapOf("changed" to false, "invalidated_analyses" to emptyList<String>(), "decision_reopened" to false)
        val invalidate = if (changed.any { it != "name" }) listOf("appraisal", "rights", "simulation") else emptyList()
        val selected = case.path("selected_property_id").asLong() == propertyId
        val previousAnalyses = rows("SELECT analysis_type AS type,status,summary,analyzed_at,reference_id FROM candidate_analyses WHERE property_id=?", propertyId)
        val previousTasks = if (selected) rows("SELECT id,title,status,checked_by,outcome,evidence_note FROM case_execution_tasks WHERE case_id=?", caseId) else emptyList()
        if (invalidate.isNotEmpty()) {
            jdbc.update("UPDATE candidate_analyses SET status='stale',updated=? WHERE property_id=? AND analysis_type IN ('appraisal','rights','simulation')", now(), propertyId)
            jdbc.update("UPDATE candidate_checklist_items SET status='todo',completed_at=null,evidence='원본 매물 변경 후 다시 확인 필요',updated=? WHERE property_id=? AND category IN ('price','funding','rights')", now(), propertyId)
            if (selected) {
                execution.reset(caseId)
                jdbc.update("UPDATE purchase_cases SET selected_property_id=null,decided_at=null,decision_reason='',status='reviewing' WHERE id=?", caseId)
                jdbc.update("UPDATE case_properties SET status='shortlisted' WHERE id=?", propertyId)
            }
        }
        val previousDecision = if (selected) json.valueToTree<JsonNode>(mapOf("property_id" to propertyId, "reason" to case.get("decision_reason"), "decided_at" to case.get("decided_at"))) else null
        jdbc.update("""INSERT INTO candidate_source_reviews(case_id,property_id,user_id,previous_snapshot,applied_snapshot,previous_decision,
            invalidated_analyses,previous_analyses,previous_execution,created) VALUES (?,?,?,?::json,?::json,?::json,?::json,?::json,?::json,?)""",
            caseId, propertyId, owner, before.toString(), after.toString(), previousDecision?.toString(), json.writeValueAsString(invalidate),
            json.writeValueAsString(previousAnalyses), json.writeValueAsString(previousTasks), now())
        jdbc.update("UPDATE case_properties SET name=?,asking_price=?,address=?,area_sqm=?,category=?,legal_region_code=?,source_snapshot=?::json,updated=? WHERE id=?",
            source.text("name"), source.amount("asking_price"), source.text("address"), source.path("area_sqm").asDouble(),
            source.text("property_type"), source.text("legal_region_code"), after.toString(), version(), propertyId)
        touch(caseId)
        return mapOf("changed" to changed.isNotEmpty(), "invalidated_analyses" to invalidate, "decision_reopened" to (selected && invalidate.isNotEmpty()))
    }
}
