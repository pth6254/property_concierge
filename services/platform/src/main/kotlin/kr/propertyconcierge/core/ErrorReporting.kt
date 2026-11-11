package kr.propertyconcierge.core

import io.sentry.Sentry
import io.sentry.SentryEvent
import io.sentry.SentryLevel
import io.sentry.protocol.Message
import jakarta.servlet.http.HttpServletRequest
import jakarta.servlet.http.HttpServletResponse
import org.slf4j.LoggerFactory
import org.springframework.core.Ordered
import org.springframework.core.env.Environment
import org.springframework.dao.DataAccessException
import org.springframework.http.converter.HttpMessageNotReadableException
import org.springframework.stereotype.Component
import org.springframework.web.ErrorResponse
import org.springframework.web.bind.MethodArgumentNotValidException
import org.springframework.web.servlet.HandlerExceptionResolver
import org.springframework.web.servlet.HandlerMapping
import org.springframework.web.servlet.ModelAndView

/**
 * 서버 오류와 화면 오류를 한 곳에서 Sentry로 보낸다. SENTRY_DSN이 없으면 초기화하지 않아 로컬·CI·테스트에 영향이 없다.
 *
 * 요청 본문·쿠키·IP·실제 URL(사용자 ID가 든 경로)은 보내지 않는다. 경로는 Spring 매핑 패턴(`/api/cases/{caseId}`)만 쓴다.
 * Python의 send_default_pii=False와 같은 원칙이다.
 */
@Component
class ErrorReporter(env: Environment) {
    private val log = LoggerFactory.getLogger(javaClass)
    val enabled: Boolean = env.getProperty("SENTRY_DSN", "").isNotBlank()

    init {
        if (enabled) {
            Sentry.init { options ->
                options.dsn = env.getProperty("SENTRY_DSN", "").trim()
                options.environment = env.getProperty("APP_ENV", "development")
                env.getProperty("SENTRY_RELEASE", "").takeIf { it.isNotBlank() }?.let { options.release = it }
                options.isSendDefaultPii = false
                options.setTag("service", "platform")
            }
            log.info("Sentry 오류 추적 활성화 (environment={})", env.getProperty("APP_ENV", "development"))
        }
    }

    fun server(error: Throwable, status: Int, route: String) {
        if (!enabled) return
        Sentry.captureException(error) { scope ->
            // ApiFailure 5xx는 외부 공급자·분석 서비스 장애처럼 예상된 저하라 경고로 구분한다.
            scope.level = if (error is ApiFailure) SentryLevel.WARNING else SentryLevel.ERROR
            scope.setTag("status", status.toString())
            scope.setTag("route", route)
        }
    }

    fun client(report: ClientErrorReport, route: String) {
        val message = clientMessage(report.message)
        if (!enabled) {
            // DSN이 없어도 운영자가 컨테이너 로그로 화면 오류를 볼 수 있게 한 줄만 남긴다. 스택은 길어서 남기지 않는다.
            log.warn("화면 오류 보고: kind={} route={} digest={} message={}", report.kind, route, report.digest ?: "-", message)
            return
        }
        val event = SentryEvent().apply {
            this.message = Message().apply { formatted = message }
            level = SentryLevel.ERROR
            setTag("source", "web")
            setTag("kind", report.kind)
            setTag("route", route)
            report.digest?.takeIf { it.isNotBlank() }?.let { setTag("digest", it) }
            report.stack?.takeIf { it.isNotBlank() }?.let { setExtra("stack", scrub(it).take(4000)) }
            // 경로·종류·문구가 같으면 한 이슈로 묶는다. 사용자마다 다른 ID가 경로에 들어가지 않도록 route는 정규화된 값이다.
            fingerprints = listOf("web", report.kind, route, message.take(120))
        }
        Sentry.captureEvent(event)
    }

    companion object {
        private val email = Regex("[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}")
        private val idSegment = Regex("^(?:[0-9]+|[0-9a-fA-F-]{16,})$")

        fun scrub(text: String): String = email.replace(text, "[email]")
        fun clientMessage(text: String): String = scrub(text.replace(Regex("\\s+"), " ").trim()).take(300).ifEmpty { "(빈 오류 메시지)" }

        /** 화면 경로의 숫자·긴 식별자 조각을 `:id`로 바꾼다. 질의 문자열·해시는 버린다. */
        fun clientRoute(path: String): String {
            val bare = path.substringBefore('?').substringBefore('#')
            if (!bare.startsWith("/")) return "/unknown"
            return bare.split('/').joinToString("/") { if (idSegment.matches(it)) ":id" else it }.take(200)
        }

        /**
         * 보고할 오류의 HTTP 상태. null이면 보고하지 않는다.
         * 4xx(입력 오류·권한·없는 자료)는 사용자 행동의 결과라 오류 추적에 넣지 않는다.
         */
        fun reportableStatus(error: Throwable): Int? = when {
            error is ApiFailure -> error.status.takeIf { it >= 500 }
            error is MethodArgumentNotValidException || error is HttpMessageNotReadableException
                || error is IllegalArgumentException || error is com.fasterxml.jackson.core.JacksonException -> null
            error is org.springframework.beans.TypeMismatchException || error is org.springframework.web.multipart.MultipartException -> null
            // 사용자가 응답 전에 연결을 끊은 경우. 서버 결함이 아니다.
            error.javaClass.simpleName in setOf("ClientAbortException", "AsyncRequestNotUsableException") -> null
            error is ErrorResponse -> error.statusCode.value().takeIf { it >= 500 }
            error is DataAccessException -> 503
            else -> 500
        }
    }
}

/** 응답은 기존 ApiFailureHandler·Spring 기본 처리에 맡기고 보고만 한다(null 반환). */
@Component
class ErrorReportingResolver(private val reporter: ErrorReporter) : HandlerExceptionResolver, Ordered {
    override fun getOrder() = Ordered.HIGHEST_PRECEDENCE

    override fun resolveException(request: HttpServletRequest, response: HttpServletResponse, handler: Any?, ex: Exception): ModelAndView? {
        val status = ErrorReporter.reportableStatus(ex) ?: return null
        runCatching {
            val route = request.getAttribute(HandlerMapping.BEST_MATCHING_PATTERN_ATTRIBUTE) as? String ?: "unmatched"
            reporter.server(ex, status, "${request.method} $route")
        }
        return null
    }
}
