package kr.propertyconcierge.core.bridge

import jakarta.servlet.http.HttpServletRequest
import jakarta.servlet.http.HttpServletResponse
import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.auth.SessionService
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController

@RestController
class TransitionController(private val python: PythonClient, private val sessions: SessionService) {
    // 이전하지 않은 경로만 중계한다. 내부 URL과 사용자 식별 헤더를 브라우저에서 지정할 수 없다.
    private val known = setOf("auth", "cases", "listings", "market", "appraisal", "recommendation", "simulation",
        "comparison", "concierge", "history", "activity", "address", "rights", "chat", "operations", "feedback", "jobs")
    @RequestMapping("/api/**")
    fun forward(request: HttpServletRequest, response: HttpServletResponse) {
        val section = request.requestURI.removePrefix("/api/").substringBefore('/')
        if (section !in known) throw ApiFailure(404, "요청 경로가 없습니다")
        val user = sessions.optional(request)
        if (section in setOf("cases", "listings", "concierge", "history", "activity", "operations", "feedback") && user == null)
            throw ApiFailure(401, "로그인이 필요합니다")
        if (section == "operations" && user != null && !sessions.operator(user)) throw ApiFailure(403, "운영자 권한이 필요합니다")
        val body = request.inputStream.readNBytes(25 * 1024 * 1024 + 1)
        if (body.size > 25 * 1024 * 1024) throw ApiFailure(413, "요청 자료가 너무 큽니다")
        val path = request.requestURI + (request.queryString?.let { "?$it" } ?: "")
        val reply = python.send(request.method, path, body,
            request.cookies?.firstOrNull { it.name == "auth_token" }?.let { "auth_token=${it.value}" }, request.contentType, request.remoteAddr)
        response.status = reply.status
        for (header in listOf("content-type", "set-cookie", "retry-after", "location", "cache-control"))
            reply.headers[header]?.forEach { response.addHeader(header, it) }
        response.outputStream.write(reply.body)
    }
}
