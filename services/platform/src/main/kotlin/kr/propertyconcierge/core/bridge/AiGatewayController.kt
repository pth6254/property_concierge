package kr.propertyconcierge.core.bridge

import jakarta.servlet.http.HttpServletRequest
import jakarta.servlet.http.HttpServletResponse
import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.auth.RedisLimits
import kr.propertyconcierge.core.auth.SessionService
import kr.propertyconcierge.core.auth.ChatQuota
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController

@RestController
class AiGatewayController(private val python: PythonClient, private val sessions: SessionService, private val limits: RedisLimits, private val quota:ChatQuota) {
    private val posts = setOf("/appraisal", "/rights/analyze", "/chat", "/concierge/messages", "/recommendation", "/recommendation/complexes", "/comparison")
    @RequestMapping("/api/appraisal", "/api/rights/analyze", "/api/chat", "/api/concierge/messages", "/api/recommendation",
        "/api/recommendation/complexes", "/api/comparison", "/api/chat/conversations/{conversationId}", "/api/concierge/conversations/{conversationId}")
    fun analyze(request: HttpServletRequest, response: HttpServletResponse) {
        val path = request.requestURI.removePrefix("/api")
        val conversation = path.startsWith("/chat/conversations/") || path.startsWith("/concierge/conversations/")
        if (request.method != (if (conversation) "GET" else "POST") || (!conversation && path !in posts)) throw ApiFailure(405, "지원하지 않는 요청 방식입니다")
        val user = if (conversation || path.startsWith("/concierge/")) sessions.required(request) else sessions.optional(request)
        if (request.method == "POST") limits.check(path, request.remoteAddr, if (path == "/chat") 10 else 5, 60)
        if (path == "/chat") quota.check(user?.id)
        val body = request.inputStream.readNBytes(25 * 1024 * 1024 + 1)
        if (body.size > 25 * 1024 * 1024) throw ApiFailure(413, "요청 자료가 너무 큽니다")
        val reply = python.send(request.method, "/internal/v1/ai$path", body, contentType=request.contentType, userId=user?.id)
        response.status = reply.status
        for (header in listOf("content-type", "retry-after", "cache-control")) reply.headers[header]?.forEach { response.addHeader(header,it) }
        response.outputStream.write(reply.body)
    }
}
