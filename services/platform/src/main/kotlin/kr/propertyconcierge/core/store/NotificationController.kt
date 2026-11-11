package kr.propertyconcierge.core.store

import jakarta.servlet.http.HttpServletRequest
import kr.propertyconcierge.core.auth.SessionService
import org.slf4j.LoggerFactory
import org.springframework.http.HttpStatus
import org.springframework.web.bind.annotation.*

@RestController
@RequestMapping("/api/notifications")
class NotificationController(private val sessions: SessionService, private val store: NotificationStore) {
    private val log = LoggerFactory.getLogger(javaClass)

    // 동기화 실패가 알림 목록·개수 조회를 막지 않게 한다. 마지막으로 저장된 알림을 보여준다.
    private fun refresh(owner: Long, interval: Long) {
        try { store.sync(owner, interval) } catch (error: RuntimeException) { log.warn("변화 알림 동기화 실패: {}", error.javaClass.simpleName) }
    }

    /** 알림함 화면: 10초 안에 다시 열면 저장된 결과를 그대로 쓴다(새로고침 연타로 반복 계산하지 않게). */
    @GetMapping
    fun list(request: HttpServletRequest): Map<String, Any?> {
        val owner = sessions.required(request).id
        refresh(owner, 10)
        return store.list(owner)
    }

    /** 메뉴의 읽지 않은 개수: 화면 이동마다 불리므로 5분에 한 번만 다시 계산한다. */
    @GetMapping("/summary")
    fun summary(request: HttpServletRequest): Map<String, Any> {
        val owner = sessions.required(request).id
        refresh(owner, 300)
        return mapOf("unread_count" to store.unread(owner))
    }

    @PostMapping("/{notificationId:[0-9]+}/read")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    fun read(request: HttpServletRequest, @PathVariable notificationId: Long) = store.read(sessions.required(request).id, notificationId)

    @PostMapping("/read-all")
    fun readAll(request: HttpServletRequest): Map<String, Any> = mapOf("updated" to store.readAll(sessions.required(request).id))
}
