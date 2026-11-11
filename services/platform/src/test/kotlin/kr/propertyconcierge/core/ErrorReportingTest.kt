package kr.propertyconcierge.core

import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.springframework.dao.DataRetrievalFailureException
import org.springframework.http.HttpStatus
import org.springframework.mock.env.MockEnvironment
import org.springframework.web.HttpRequestMethodNotSupportedException
import org.springframework.web.server.ResponseStatusException
import org.springframework.web.servlet.resource.NoResourceFoundException
import org.springframework.http.HttpMethod

class ErrorReportingTest {
    @Test fun `사용자 입력·권한·없는 자료는 보고하지 않고 서버 결함만 보고한다`() {
        assertNull(ErrorReporter.reportableStatus(ApiFailure(404, "없음")))
        assertNull(ErrorReporter.reportableStatus(ApiFailure(429, "제한")))
        assertNull(ErrorReporter.reportableStatus(IllegalArgumentException("입력")))
        assertNull(ErrorReporter.reportableStatus(HttpRequestMethodNotSupportedException("PUT")))
        assertNull(ErrorReporter.reportableStatus(NoResourceFoundException(HttpMethod.GET, "/api/none")))
        assertNull(ErrorReporter.reportableStatus(ResponseStatusException(HttpStatus.FORBIDDEN)))

        assertEquals(502, ErrorReporter.reportableStatus(ApiFailure(502, "외부 조회 실패")))
        assertEquals(503, ErrorReporter.reportableStatus(DataRetrievalFailureException("db")))
        assertEquals(500, ErrorReporter.reportableStatus(IllegalStateException("결함")))
        assertEquals(500, ErrorReporter.reportableStatus(NullPointerException()))
    }

    @Test fun `화면 경로의 식별자·질의 문자열은 보내지 않는다`() {
        assertEquals("/cases/:id/summary", ErrorReporter.clientRoute("/cases/123/summary?tab=price#axis"))
        assertEquals("/report/:id", ErrorReporter.clientRoute("/report/3f2b9c1e-0d4a-4b7e-9f00-1234567890ab"))
        assertEquals("/listings", ErrorReporter.clientRoute("/listings"))
        assertEquals("/unknown", ErrorReporter.clientRoute("https://evil.example/cases/1"))
    }

    @Test fun `오류 문구의 이메일은 가리고 길이를 제한한다`() {
        assertEquals("[email] 계정 오류", ErrorReporter.clientMessage("  user.name+tag@example.co.kr\n 계정 오류 "))
        assertEquals(300, ErrorReporter.clientMessage("가".repeat(1000)).length)
        assertEquals("(빈 오류 메시지)", ErrorReporter.clientMessage("   "))
    }

    @Test fun `DSN이 없으면 Sentry를 초기화하지 않는다`() {
        val reporter = ErrorReporter(MockEnvironment())
        assertFalse(reporter.enabled)
        // 비활성 상태의 보고는 예외 없이 로그만 남긴다.
        reporter.server(IllegalStateException("x"), 500, "GET /api/x")
        reporter.client(ClientErrorReport("window", "boom", "/cases/1"), "/cases/:id")
    }
}
