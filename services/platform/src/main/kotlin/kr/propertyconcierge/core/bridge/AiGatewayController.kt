package kr.propertyconcierge.core.bridge

import jakarta.servlet.http.HttpServletRequest
import jakarta.servlet.http.HttpServletResponse
import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.auth.RedisLimits
import kr.propertyconcierge.core.auth.SessionService
import kr.propertyconcierge.core.auth.AiQuota
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController

@RestController
class AiGatewayController(private val python: PythonClient, private val sessions: SessionService, private val limits: RedisLimits, private val quota: AiQuota) {
    private val posts = setOf("/appraisal", "/rights/analyze", "/chat", "/concierge/messages", "/recommendation", "/recommendation/complexes", "/comparison")
    @RequestMapping("/api/appraisal", "/api/rights/analyze", "/api/chat", "/api/concierge/messages", "/api/recommendation",
        "/api/recommendation/complexes", "/api/comparison", "/api/chat/conversations/{conversationId}", "/api/concierge/conversations/{conversationId}")
    fun analyze(request: HttpServletRequest, response: HttpServletResponse) {
        val path = request.requestURI.removePrefix("/api")
        val conversation = path.startsWith("/chat/conversations/") || path.startsWith("/concierge/conversations/")
        if (request.method != (if (conversation) "GET" else "POST") || (!conversation && path !in posts)) throw ApiFailure(405, "지원하지 않는 요청 방식입니다")
        // 분석 요청은 모두 로그인이 필요하다. 화면은 이미 로그인 사용자만 쓰며, 비로그인 직접 호출이 유료 모델 비용을 쓰지 못하게 한다.
        val user = sessions.required(request)
        if (request.method == "POST") {
            limits.check(path, request.remoteAddr, if (path == "/chat") 10 else 5, 60)
            quota.check(user.id, FEATURES.getValue(path))
        }
        val body = request.inputStream.readNBytes(25 * 1024 * 1024 + 1)
        if (body.size > 25 * 1024 * 1024) throw ApiFailure(413, "요청 자료가 너무 큽니다")
        val reply = python.send(request.method, "/internal/v1/ai$path", body, contentType=request.contentType, userId=user.id)
        response.status = reply.status
        for (header in listOf("content-type", "retry-after", "cache-control")) reply.headers[header]?.forEach { response.addHeader(header,it) }
        response.outputStream.write(reply.body)
    }

    companion object {
        // 경로별 하루 한도 항목(AiQuota.DEFAULTS)
        private val FEATURES = mapOf("/appraisal" to "appraisal", "/rights/analyze" to "rights", "/chat" to "chat",
            "/concierge/messages" to "concierge", "/recommendation" to "recommendation", "/recommendation/complexes" to "recommendation",
            "/comparison" to "comparison")
    }
}
