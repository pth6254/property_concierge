package kr.propertyconcierge.core.store

import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class NotificationStoreTest {
    private fun condition(kind: String, subject: String, fingerprint: String, link: String = "/cases/1#candidate-2") =
        NotificationCondition(kind, subject, fingerprint, "제목", "본문", link, 1, 2, null)

    @Test fun `상태 조건은 사라지면 해결하고 실거래 알림은 대체되거나 대상이 아닐 때만 해결한다`() {
        val open = listOf(
            OpenNotification(1, "analysis_expired", "candidate:2:rights", "a|expired"),   // 다시 분석함 → 해결
            OpenNotification(2, "listing_reconfirm", "listing:9", "t1|age"),               // 아직 성립 → 유지
            OpenNotification(3, "trade_update", "candidate:2:trades", "100"),             // 더 새 거래 → 대체
            OpenNotification(4, "trade_update", "candidate:5:trades", "200"),             // 새 거래 없음, 대상 유지 → 유지
            OpenNotification(5, "trade_update", "candidate:7:trades", "300"),             // 제외·삭제된 후보 → 해결
            OpenNotification(6, "source_changed", "candidate:2:source", "rev:1:asking_price"), // 다른 변경으로 바뀜 → 해결
        )
        val current = listOf(condition("listing_reconfirm", "listing:9", "t1|age"), condition("trade_update", "candidate:2:trades", "150"),
            condition("source_changed", "candidate:2:source", "rev:2:asking_price,status"))
        val resolved = NotificationStore.resolutions(open, current, setOf("candidate:2:trades", "candidate:5:trades"))
        assertEquals(listOf(1L, 3L, 5L, 6L), resolved)
    }

    @Test fun `내부 경로가 아닌 링크와 알 수 없는 종류는 저장하지 않는다`() {
        assertTrue(NotificationStore.valid(condition("trade_update", "candidate:2:trades", "1")))
        assertTrue(NotificationStore.valid(condition("listing_reconfirm", "listing:9", "x", "/listings?listing_id=9#saved-listings")))
        assertFalse(NotificationStore.valid(condition("trade_update", "candidate:2:trades", "1", "//evil.example/x")))
        assertFalse(NotificationStore.valid(condition("trade_update", "candidate:2:trades", "1", "https://evil.example")))
        assertFalse(NotificationStore.valid(condition("price_drop", "candidate:2", "1")))
        assertFalse(NotificationStore.valid(condition("trade_update", "", "1")))
    }
}
