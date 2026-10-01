package kr.propertyconcierge.core.feedback

import jakarta.servlet.http.HttpServletRequest
import jakarta.validation.Valid
import jakarta.validation.constraints.Size
import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.auth.RedisLimits
import kr.propertyconcierge.core.auth.SessionService
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.web.bind.annotation.*
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

data class FeedbackInput(val feature: String, val category: String, @field:Size(min=3,max=2000) val message: String)
data class FeedbackUpdate(val status: String)

@RestController
class FeedbackController(private val jdbc: JdbcTemplate, private val sessions: SessionService, private val limits: RedisLimits) {
    private val fields = "id,feature,category,message,status,created"
    private fun operator(request: HttpServletRequest) = sessions.required(request).also {
        if (!sessions.operator(it)) throw ApiFailure(403, "운영자 권한이 필요합니다")
    }
    @PostMapping("/api/feedback")
    @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
    fun create(request: HttpServletRequest, @Valid @RequestBody body: FeedbackInput): Map<String, Any?> {
        val owner = sessions.required(request).id
        limits.check("feedback", request.remoteAddr, 10, 3600)
        if (body.feature !in setOf("explore","recommendation","cases","appraisal","simulation","rights","chat","listings","other")
            || body.category !in setOf("error","confusing","incorrect","suggestion") || body.message.trim().length < 3) throw ApiFailure(422, "문제 신고 내용을 확인해주세요")
        val id = jdbc.queryForObject("INSERT INTO service_feedback(user_id,feature,category,message,status,created) VALUES (?,?,?,?,'open',?) RETURNING id",
            Long::class.java, owner, body.feature, body.category, body.message.trim(), LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")))
        return jdbc.queryForList("SELECT $fields FROM service_feedback WHERE id=? AND user_id=?", id, owner).first()
    }
    @GetMapping("/api/feedback")
    fun mine(request: HttpServletRequest) = mapOf("items" to jdbc.queryForList("SELECT $fields FROM service_feedback WHERE user_id=? ORDER BY id DESC LIMIT 30", sessions.required(request).id))
    @GetMapping("/api/operations/feedback")
    fun inbox(request: HttpServletRequest): Map<String, Any> { operator(request); return mapOf("items" to jdbc.queryForList("SELECT $fields FROM service_feedback ORDER BY id DESC LIMIT 100")) }
    @PatchMapping("/api/operations/feedback/{feedbackId:[0-9]+}")
    fun update(request: HttpServletRequest, @PathVariable feedbackId: Long, @RequestBody body: FeedbackUpdate): Map<String, Any?> {
        operator(request)
        if (body.status !in setOf("open","reviewing","resolved")) throw ApiFailure(422, "처리 상태를 확인해주세요")
        if (jdbc.update("UPDATE service_feedback SET status=? WHERE id=?", body.status, feedbackId) == 0) throw ApiFailure(404, "문제 신고가 없습니다")
        return jdbc.queryForList("SELECT $fields FROM service_feedback WHERE id=?", feedbackId).first()
    }
}
