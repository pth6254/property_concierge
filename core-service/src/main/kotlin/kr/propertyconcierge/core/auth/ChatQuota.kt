package kr.propertyconcierge.core.auth

import kr.propertyconcierge.core.ApiFailure
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.stereotype.Service
import java.time.LocalDate

@Service
class ChatQuota(private val jdbc:JdbcTemplate) {
    fun check(userId:Long?) {
        if(userId==null) return
        val count=jdbc.queryForObject("SELECT count(*) FROM activity WHERE user_id=? AND type='chat' AND created LIKE ?",Long::class.java,userId,"${LocalDate.now()}%") ?: 0
        if(count>=50) throw ApiFailure(429,"오늘 상담 횟수(50회)를 모두 사용했습니다. 내일 다시 이용해주세요.")
    }
}
