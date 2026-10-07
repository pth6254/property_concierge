package kr.propertyconcierge.core.addresses

import jakarta.servlet.http.HttpServletRequest
import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.auth.RedisLimits
import org.springframework.core.env.Environment
import org.springframework.web.bind.annotation.*
import java.security.MessageDigest

@RestController
class LandInformationController(private val land: LandInformationService, private val limits: RedisLimits, env: Environment) {
    private val key = env.getRequiredProperty("INTERNAL_SERVICE_SECRET")
    @PostMapping("/api/address/land")
    fun lookup(@RequestBody body: LandLookupInput, request: HttpServletRequest): Any {
        limits.check("land-information", request.remoteAddr, 20, 60)
        return land.lookup(body)
    }
    @PostMapping("/internal/v1/land/lookup")
    fun internal(@RequestBody body: LandLookupInput, @RequestHeader("X-Internal-Service-Key", required=false) provided: String?): Any {
        if (provided == null || !MessageDigest.isEqual(key.toByteArray(), provided.toByteArray())) throw ApiFailure(401, "내부 서비스 인증이 필요합니다")
        return land.lookup(body)
    }
}
