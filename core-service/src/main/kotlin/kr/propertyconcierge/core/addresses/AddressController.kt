package kr.propertyconcierge.core.addresses

import jakarta.servlet.http.HttpServletRequest
import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.auth.SessionService
import org.springframework.core.env.Environment
import org.springframework.web.bind.annotation.*
import java.security.MessageDigest

@RestController
class AddressController(private val addresses: ListingAddressService, private val sessions: SessionService, env: Environment) {
    private val key = env.getRequiredProperty("INTERNAL_SERVICE_SECRET")
    @GetMapping("/api/address/search")
    fun raw(@RequestParam query: String, @RequestParam(defaultValue="keyword") type: String): Any {
        if (type !in setOf("address", "keyword") || query.length > 200) throw ApiFailure(422, "주소 검색 조건을 확인해주세요")
        return if (query.isBlank()) mapOf("documents" to emptyList<Any>(), "meta" to mapOf("total_count" to 0)) else addresses.kakao(query, type, 15)
    }
    @GetMapping("/api/listings/address/search")
    fun search(@RequestParam query: String, request: HttpServletRequest) = addresses.search(query, sessions.required(request).id)
    @PostMapping("/internal/v1/addresses/verify")
    fun verify(@RequestBody body: AddressProofInput, @RequestHeader("X-Internal-Service-Key", required=false) provided: String?): ListingAddressValue {
        if (provided == null || !MessageDigest.isEqual(key.toByteArray(), provided.toByteArray())) throw ApiFailure(401, "내부 서비스 인증이 필요합니다")
        return addresses.verify(body.token, body.userId)
    }
}
