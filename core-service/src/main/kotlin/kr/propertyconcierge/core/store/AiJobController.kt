package kr.propertyconcierge.core.store

import jakarta.annotation.PreDestroy
import jakarta.servlet.http.HttpServletRequest
import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.auth.SessionService
import org.springframework.http.MediaType
import org.springframework.web.bind.annotation.*
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

@RestController
class AiJobController(private val jobs: AiJobStore, private val sessions: SessionService) {
    private val timers = Executors.newScheduledThreadPool(2)
    @PreDestroy fun stop() { timers.shutdownNow() }
    @GetMapping("/api/appraisal/jobs/{jobId:[0-9a-f]{16}}", "/api/chat/jobs/{jobId:[0-9a-f]{16}}", "/api/concierge/jobs/{jobId:[0-9a-f]{16}}", "/api/listings/collection/jobs/{jobId:[0-9a-f]{16}}")
    fun status(request: HttpServletRequest, @PathVariable jobId: String): com.fasterxml.jackson.databind.JsonNode {
        // 매물 수집은 로그인 전용이며, 공개 AI 작업의 익명 조회 정책과 구분한다.
        val owner = if (request.requestURI.startsWith("/api/listings/collection/")) sessions.required(request).id
            else sessions.optional(request)?.id
        return jobs.get(jobId, owner) ?: throw ApiFailure(404, "작업이 없거나 만료되었습니다")
    }

    // 실제 작업은 Redis·별도 Python 실행기에 유지된다. SSE 연결 종료는 작업 취소가 아니다.
    @GetMapping("/api/jobs/{jobId:[0-9a-f]{16}}/events", produces=[MediaType.TEXT_EVENT_STREAM_VALUE])
    fun events(request: HttpServletRequest, @PathVariable jobId: String): SseEmitter {
        status(request, jobId)
        val emitter = SseEmitter(120000)
        val closed = AtomicBoolean(false)
        val timer = AtomicReference<ScheduledFuture<*>?>()
        fun close() { closed.set(true); timer.get()?.cancel(false) }
        emitter.onCompletion(::close); emitter.onTimeout(::close); emitter.onError { close() }
        var previous = ""
        val future = timers.scheduleWithFixedDelay({
            if (closed.get()) { timer.get()?.cancel(false); return@scheduleWithFixedDelay }
            try {
                val value = status(request, jobId)
                val current = value.toString()
                if (previous != current) {
                    emitter.send(SseEmitter.event().name("job").data(value)); previous = current
                }
                if (value.path("status").asText() in setOf("done", "error")) { close(); emitter.complete() }
            } catch (error: Exception) { close(); emitter.completeWithError(error) }
        }, 0, 500, TimeUnit.MILLISECONDS)
        timer.set(future)
        if (closed.get()) future.cancel(false)
        return emitter
    }
}
