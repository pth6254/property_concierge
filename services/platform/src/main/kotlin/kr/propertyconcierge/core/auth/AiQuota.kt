package kr.propertyconcierge.core.auth

import kr.propertyconcierge.core.ApiFailure
import org.springframework.core.env.Environment
import org.springframework.data.redis.core.StringRedisTemplate
import org.springframework.data.redis.core.script.DefaultRedisScript
import org.springframework.stereotype.Service
import java.time.LocalDate
import java.time.ZoneId

/**
 * AI·분석 기능의 사용자별 하루 이용 한도.
 *
 * IP당 분당 제한(RedisLimits)만으로는 한 계정이 하루 종일 유료 모델 호출을 이어갈 수 있다. 기능마다 하루 한도를 두고
 * 한국 날짜(Asia/Seoul) 기준으로 초기화한다. 서버 시간대와 무관하게 자정에 바뀐다.
 * 요청을 접수할 때 센다(작업이 실패해도 차감). 한도는 `AI_DAILY_LIMIT_<기능>` 환경변수로 바꿀 수 있다.
 */
@Service
class AiQuota(private val redis: StringRedisTemplate, private val env: Environment) {
    private val increment = DefaultRedisScript(
        "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n", Long::class.java)

    fun check(userId: Long, feature: String) {
        val default = DEFAULTS[feature] ?: error("한도가 정의되지 않은 기능: $feature")
        val limit = env.getProperty("AI_DAILY_LIMIT_${feature.uppercase()}", Long::class.java, default)
        val day = LocalDate.now(SEOUL)
        val used = redis.execute(increment, listOf("ai-quota:$feature:$userId:$day"), (2 * 86400).toString()) ?: limit + 1
        if (used > limit) throw ApiFailure(429, "오늘 ${LABELS[feature]} 이용 한도(${limit}회)를 모두 사용했습니다. 내일 다시 이용해주세요.")
    }

    companion object {
        private val SEOUL: ZoneId = ZoneId.of("Asia/Seoul")
        val DEFAULTS = mapOf("chat" to 50L, "concierge" to 50L, "appraisal" to 30L, "recommendation" to 30L,
            "comparison" to 30L, "rights" to 20L)
        private val LABELS = mapOf("chat" to "법률·세금 상담", "concierge" to "AI 컨시어지", "appraisal" to "시세추정",
            "recommendation" to "단지 추천", "comparison" to "매물 비교", "rights" to "권리관계 점검")
    }
}
