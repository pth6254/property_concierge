package kr.propertyconcierge.core

import org.springframework.data.redis.core.StringRedisTemplate
import org.springframework.http.ResponseEntity
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RestController
import kr.propertyconcierge.core.bridge.PythonClient

@RestController
class HealthController(private val jdbc: JdbcTemplate, private val redis: StringRedisTemplate, private val python: PythonClient) {
    @GetMapping("/health")
    fun health() = mapOf("status" to "ok")
    @GetMapping("/ready")
    fun ready(): ResponseEntity<Map<String, String>> {
        val ready = runCatching { jdbc.queryForObject("SELECT 1", Int::class.java) == 1 &&
            redis.execute { it.ping() } == "PONG" && python.send("GET", "/ready", timeoutSeconds=5).status == 200 }.getOrDefault(false)
        return ResponseEntity.status(if (ready) 200 else 503).body(mapOf("status" to if (ready) "ready" else "not_ready"))
    }
}
