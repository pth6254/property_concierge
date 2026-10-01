package kr.propertyconcierge.core

import org.springframework.core.env.Environment
import org.springframework.data.redis.core.StringRedisTemplate
import org.springframework.stereotype.Service
import org.springframework.data.redis.core.script.DefaultRedisScript
import java.security.MessageDigest
import java.time.Duration
import java.time.LocalDate
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

@Service
class CoreUsageMetrics(private val redis: StringRedisTemplate, env: Environment) {
    private val salt = env.getRequiredProperty("JWT_SECRET_KEY")
    private val duration = DefaultRedisScript("""
        redis.call('HINCRBY',KEYS[1],'requests',1)
        redis.call('HINCRBY',KEYS[1],'failures',ARGV[1])
        redis.call('HINCRBYFLOAT',KEYS[1],'total_seconds',ARGV[2])
        redis.call('HINCRBY',KEYS[1],ARGV[3],1)
        redis.call('EXPIRE',KEYS[1],ARGV[4])
        redis.call('SADD',KEYS[2],ARGV[5])
        redis.call('EXPIRE',KEYS[2],ARGV[4])
        return 1
    """.trimIndent(), Long::class.java)
    fun request(method: String, template: String, elapsed: Double, status: Int) {
        runCatching {
            val feature = "http:$method:$template"
            val day = LocalDate.now(ZoneOffset.UTC).format(DateTimeFormatter.BASIC_ISO_DATE)
            val bucket = listOf(0.1,0.5,1.0,3.0,10.0,30.0,60.0,120.0,300.0,900.0).firstOrNull { elapsed <= it }?.let {
                // Python 운영 화면의 버킷 필드 이름과 같은 계약을 사용한다.
                if (it in setOf(0.1,0.5)) it.toString() else it.toLong().toString()
            } ?: "overflow"
            redis.execute(duration, listOf("metrics:duration:$day:$feature", "metrics:features:$day"),
                if (status >= 500) "1" else "0", elapsed.toString(), "bucket:$bucket", "3024000", feature)
        }.onFailure { org.slf4j.LoggerFactory.getLogger(javaClass).warn("요청 집계 실패") }
    }
    fun step(name: String, userId: Long) {
        runCatching {
            val digest = MessageDigest.getInstance("SHA-256").digest("$salt:$userId".toByteArray()).joinToString("") { "%02x".format(it) }
            val day = LocalDate.now(ZoneOffset.UTC).format(DateTimeFormatter.BASIC_ISO_DATE)
            val key = "metrics:step:$day:$name"
            redis.opsForSet().add(key, digest); redis.expire(key, Duration.ofDays(35))
        }.onFailure { org.slf4j.LoggerFactory.getLogger(javaClass).warn("사용 단계 집계 실패") }
    }
}
