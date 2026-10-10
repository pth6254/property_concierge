package kr.propertyconcierge.core.listings

import jakarta.servlet.http.HttpServletRequest
import jakarta.validation.Valid
import jakarta.validation.constraints.NotBlank
import jakarta.validation.constraints.Size
import kr.propertyconcierge.core.auth.SessionService
import org.springframework.web.bind.annotation.*

data class ImportInput(@field:NotBlank @field:Size(max=100) val sourceName: String,
    @field:NotBlank @field:Size(max=1_000_000) val csvText: String, val commit: Boolean = false)

data class ConfirmInput(@field:NotBlank @field:Size(max=40) val confirmedAt: String, @field:NotBlank @field:Size(max=20) val status: String,
    val askingPrice: Long? = null, val deposit: Long? = null, val monthlyRent: Long? = null)

@RestController
@RequestMapping("/api/listings")
class ListingController(private val listings: ListingService, private val sessions: SessionService) {
    @GetMapping
    fun search(request: HttpServletRequest,
        @RequestParam("region_code", required=false) region: String?, @RequestParam("property_type", required=false) type: String?,
        @RequestParam("transaction_type", required=false) transaction: String?, @RequestParam(required=false) status: String?,
        @RequestParam("budget_max", required=false) budget: Long?, @RequestParam("area_min", required=false) area: Double?,
        @RequestParam("fresh_only", defaultValue="false") fresh: Boolean,
        @RequestParam(defaultValue="1") page: Int, @RequestParam("page_size", defaultValue="20") size: Int) =
        listings.search(sessions.required(request).id, ListingFilters(region, type, transaction, status, budget, area, fresh, page, size))
    @GetMapping("/{id:[0-9]+}")
    fun get(@PathVariable id: Long, request: HttpServletRequest) = listings.get(sessions.required(request).id, id)
    @GetMapping("/{id:[0-9]+}/history")
    fun history(@PathVariable id: Long, request: HttpServletRequest) = listings.history(sessions.required(request).id, id)
    @GetMapping("/{id:[0-9]+}/timeline")
    fun timeline(@PathVariable id: Long, request: HttpServletRequest) = listings.timeline(sessions.required(request).id, id)
    @GetMapping("/{id:[0-9]+}/market-overlay")
    fun marketOverlay(@PathVariable id: Long, request: HttpServletRequest) = listings.marketOverlay(sessions.required(request).id, id)
    @PostMapping("/{id:[0-9]+}/confirm")
    fun confirm(@PathVariable id: Long, @Valid @RequestBody body: ConfirmInput, request: HttpServletRequest) =
        listings.confirm(sessions.required(request).id, id, ListingConfirmation(body.confirmedAt, body.status, body.askingPrice, body.deposit, body.monthlyRent))
    @PostMapping("/import")
    fun import(@Valid @RequestBody body: ImportInput, request: HttpServletRequest) =
        listings.import(sessions.required(request).id, body.sourceName, body.csvText, body.commit)
}
