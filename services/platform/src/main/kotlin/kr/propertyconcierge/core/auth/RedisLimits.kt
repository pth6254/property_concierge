package kr.propertyconcierge.core.auth

import kr.propertyconcierge.core.ApiFailure
import org.springframework.core.env.Environment
import org.springframework.data.redis.core.StringRedisTemplate
import org.springframework.data.redis.core.script.DefaultRedisScript
import org.springframework.stereotype.Service

@Service
class RedisLimits(private val redis: StringRedisTemplate, env: Environment) {
    private val disabled = env.getProperty("DISABLE_RATE_LIMIT", "0") == "1"
    private val increment = DefaultRedisScript("local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n", Long::class.java)
    fun check(scope: String, actor: String, limit: Long, seconds: Long) {
        if (disabled) return
        if ((redis.execute(increment, listOf("core-limit:$scope:$actor"), seconds.toString()) ?: limit + 1) > limit)
            throw ApiFailure(429, "요청이 너무 많습니다. 잠시 후 다시 시도해주세요")
    }
    fun lock(email: String) {
        if ((redis.opsForValue().get("loginfail:$email")?.toLongOrNull() ?: 0) >= 5)
            throw ApiFailure(429, "로그인 시도가 너무 많습니다. 10분 후 다시 시도해주세요.")
    }
    fun failed(email: String) { redis.execute(increment, listOf("loginfail:$email"), "600") }
    fun clear(email: String) { redis.delete("loginfail:$email") }
}
