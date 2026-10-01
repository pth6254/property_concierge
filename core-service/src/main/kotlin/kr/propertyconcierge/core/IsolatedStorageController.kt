package kr.propertyconcierge.core

import org.springframework.core.env.Environment
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.web.bind.annotation.*
import java.net.URI
import java.security.MessageDigest

/** 테스트가 운영 HTTP 저장소에 쓰지 않도록 실제 연결된 저장소를 대조한다. */
@RestController
class IsolatedStorageController(private val jdbc: JdbcTemplate, private val env: Environment) {
    @GetMapping("/internal/v1/testing/storage")
    fun storage(@RequestHeader("X-Internal-Service-Key", required = false) provided: String?): Map<String, Any> {
        val key = env.getRequiredProperty("INTERNAL_SERVICE_SECRET")
        if (provided == null || !MessageDigest.isEqual(key.toByteArray(), provided.toByteArray())) throw ApiFailure(401, "내부 인증이 필요합니다")
        val database = jdbc.queryForObject("SELECT current_database()", String::class.java)
        val redis = URI(env.getRequiredProperty("REDIS_URL")).path
        if (database != "real_estate_test" || redis != "/15") throw ApiFailure(403, "격리 테스트 저장소가 아닙니다")
        return mapOf("database" to database, "redis_database" to 15)
    }
}
