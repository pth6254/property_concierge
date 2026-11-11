package kr.propertyconcierge.core

import jakarta.servlet.http.HttpServletRequest
import jakarta.validation.Valid
import jakarta.validation.constraints.Size
import kr.propertyconcierge.core.auth.RedisLimits
import org.springframework.http.HttpStatus
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.ResponseStatus
import org.springframework.web.bind.annotation.RestController

data class ClientErrorReport(
    @field:Size(min = 1, max = 20) val kind: String,
    @field:Size(max = 2000) val message: String,
    @field:Size(max = 300) val path: String,
    @field:Size(max = 100) val digest: String? = null,
    @field:Size(max = 8000) val stack: String? = null,
)

/**
 * 브라우저 오류를 Spring을 거쳐 Sentry로 보낸다(같은 출처 /api).
 * 브라우저에 DSN·Sentry SDK를 두지 않아 CSP를 'self'로 유지하고 광고 차단기에 막히지 않는다.
 * 로그인 화면의 오류도 받아야 하므로 로그인을 요구하지 않고 IP별로 제한한다.
 */
@RestController
class ClientErrorController(private val limits: RedisLimits, private val reporter: ErrorReporter) {
    @PostMapping("/api/client-errors")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    fun report(request: HttpServletRequest, @Valid @RequestBody body: ClientErrorReport) {
        limits.check("client-error", request.remoteAddr, 30, 600)
        if (body.kind !in KINDS) throw ApiFailure(422, "오류 종류를 확인해주세요")
        reporter.client(body, ErrorReporter.clientRoute(body.path))
    }

    companion object {
        // boundary: 화면 구역 오류, global: 루트 레이아웃 오류, window: 처리되지 않은 오류, promise: 처리되지 않은 비동기 거부
        val KINDS = setOf("boundary", "global", "window", "promise")
    }
}
