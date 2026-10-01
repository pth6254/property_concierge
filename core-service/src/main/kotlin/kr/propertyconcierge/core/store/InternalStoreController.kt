package kr.propertyconcierge.core.store

import com.fasterxml.jackson.databind.JsonNode
import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.listings.ListingService
import kr.propertyconcierge.core.listings.ListingFilters
import kr.propertyconcierge.core.listings.ListingObservationStore
import org.springframework.core.env.Environment
import org.springframework.web.bind.annotation.*
import java.security.MessageDigest

@RestController
@RequestMapping("/internal/v1/store")
class InternalStoreController(private val cases: CaseStore, private val execution: ExecutionStore,
    private val accounts: AccountStore, private val histories: AnalysisHistoryStore, private val listings: ListingService,
    private val observations: ListingObservationStore, private val jobs: AiJobStore, env: Environment) {
    private val key = env.getRequiredProperty("INTERNAL_SERVICE_SECRET")
    private fun requireService(provided: String?) {
        if (provided == null || !MessageDigest.isEqual(key.toByteArray(), provided.toByteArray())) throw ApiFailure(401, "내부 서비스 인증이 필요합니다")
    }
    @PostMapping("/cases/{operation}")
    fun cases(@PathVariable operation: String, @RequestBody args: JsonNode,
        @RequestHeader("X-Internal-Service-Key", required=false) provided: String?): Any? {
        requireService(provided)
        return cases.dispatch(operation, args)
    }
    @PostMapping("/execution/{operation}")
    fun execution(@PathVariable operation: String, @RequestBody args: JsonNode,
        @RequestHeader("X-Internal-Service-Key", required=false) provided: String?): Any? {
        requireService(provided)
        return execution.dispatch(operation, args)
    }
    @PostMapping("/accounts/{operation}")
    fun accounts(@PathVariable operation: String, @RequestBody args: JsonNode,
        @RequestHeader("X-Internal-Service-Key", required=false) provided: String?): Any? {
        requireService(provided)
        return accounts.dispatch(operation, args)
    }
    @PostMapping("/history/{operation}")
    fun history(@PathVariable operation: String, @RequestBody args: JsonNode,
        @RequestHeader("X-Internal-Service-Key", required=false) provided: String?): Any? {
        requireService(provided)
        return histories.history(operation, args)
    }
    @PostMapping("/activity/{operation}")
    fun activity(@PathVariable operation: String, @RequestBody args: JsonNode,
        @RequestHeader("X-Internal-Service-Key", required=false) provided: String?): Any? {
        requireService(provided)
        return histories.activity(operation, args)
    }
    @PostMapping("/observations/{operation}")
    fun observations(@PathVariable operation: String, @RequestBody args: JsonNode,
        @RequestHeader("X-Internal-Service-Key", required=false) provided: String?): Any? {
        requireService(provided)
        return observations.dispatch(operation, args)
    }
    @PostMapping("/jobs/{operation}")
    fun jobs(@PathVariable operation: String, @RequestBody args: JsonNode,
        @RequestHeader("X-Internal-Service-Key", required=false) provided: String?): Any? {
        requireService(provided)
        return jobs.dispatch(operation, args)
    }
    @PostMapping("/listings/{operation}")
    fun listings(@PathVariable operation: String, @RequestBody args: JsonNode,
        @RequestHeader("X-Internal-Service-Key", required=false) provided: String?): Any? {
        requireService(provided)
        val owner = args.path("user_id").asLong()
        if (owner <= 0) throw ApiFailure(422, "매물 소유자가 필요합니다")
        fun text(key: String) = args.get(key)?.takeUnless(JsonNode::isNull)?.asText()
        fun amount(key: String) = args.get(key)?.takeUnless(JsonNode::isNull)?.asLong()
        return when (operation) {
            "import_csv" -> listings.import(owner, args.path("source_name").asText(), args.path("csv_text").asText(), args.path("commit").asBoolean())
            "get_listing" -> listings.get(owner, args.path("listing_id").asLong())
            "listing_history" -> listings.history(owner, args.path("listing_id").asLong())
            "search_listings" -> listings.search(owner, ListingFilters(text("region_code"), text("property_type"), text("transaction_type"), text("status"),
                amount("budget_max"), args.get("area_min")?.takeUnless(JsonNode::isNull)?.asDouble(), args.path("fresh_only").asBoolean(),
                args.path("page").asInt(1), args.path("page_size").asInt(20)))
            else -> throw ApiFailure(404, "매물 저장 경로가 없습니다")
        }
    }
}
