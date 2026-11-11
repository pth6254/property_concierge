package kr.propertyconcierge.core

import kr.propertyconcierge.core.integration.PlatformIntegrationSupport
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class ClientErrorIT : PlatformIntegrationSupport() {
    @Test fun `화면 오류는 로그인 없이 받고 형식이 다르면 거부한다`() {
        request("POST", "/api/client-errors", mapOf("kind" to "boundary", "message" to "x is undefined", "path" to "/cases/7/summary",
            "digest" to "123456", "stack" to "TypeError: x is undefined\n at a (b.js:1:2)"), expected = 204)
        request("POST", "/api/client-errors", mapOf("kind" to "window", "message" to "", "path" to "/"), expected = 204)
        request("POST", "/api/client-errors", mapOf("kind" to "other", "message" to "m", "path" to "/"), expected = 422)
        request("POST", "/api/client-errors", mapOf("kind" to "window", "message" to "m"), expected = 422)
        request("POST", "/api/client-errors", mapOf("kind" to "window", "message" to "m", "path" to "/", "user" to "a@b.c"), expected = 422)
        request("POST", "/api/client-errors", mapOf("kind" to "window", "message" to "m".repeat(2001), "path" to "/"), expected = 422)
    }

    @Test fun `오류 보고 처리기는 기존 응답 상태를 바꾸지 않는다`() {
        // 보고용 처리기가 먼저 실행돼도 예외를 해결하지 않으므로 인증·입력·없는 경로의 상태는 그대로다.
        request("GET", "/api/auth/me", expected = 401)
        request("GET", "/api/cases/999999", cookie = register().second, expected = 404)
        request("POST", "/api/auth/login", mapOf("email" to "x@example.com"), expected = 422)
        assertEquals(204, request("POST", "/api/client-errors", mapOf("kind" to "promise", "message" to "m", "path" to "/x"), expected = 204).response.status)
    }
}
