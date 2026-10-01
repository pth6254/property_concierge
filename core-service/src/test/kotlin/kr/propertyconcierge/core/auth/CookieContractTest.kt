package kr.propertyconcierge.core.auth

import kr.propertyconcierge.core.CoreConfiguration
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.mockito.Mockito.mock
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.mock.env.MockEnvironment
import org.springframework.mock.web.MockHttpServletResponse

class CookieContractTest {
    private fun sessions(site: String?, mode: String = "development"): SessionService {
        val env = MockEnvironment().withProperty("JWT_SECRET_KEY", "isolated-cookie-test-key").withProperty("APP_ENV", mode)
        site?.let { env.withProperty("COOKIE_SAMESITE", it) }
        return SessionService(mock(JdbcTemplate::class.java), CoreConfiguration().objectMapper(), env)
    }
    @Test fun `개발 기본 쿠키와 운영 쿠키 보안을 구분한다`() {
        assertEquals("lax", sessions(null).sameSite)
        assertFalse(sessions(null).secure)
        assertTrue(sessions("lax", "production").secure)
    }
    @Test fun `사이트 간 쿠키는 HTTPS를 강제하고 오타는 기동을 막는다`() {
        assertEquals("none", sessions("  NONE  ").sameSite)
        assertTrue(sessions("none").secure)
        assertEquals("strict", sessions("strict").sameSite)
        assertThrows(IllegalArgumentException::class.java) { sessions("lax; strict") }
    }
    @Test fun `로그아웃의 실제 삭제 헤더도 같은 보안 속성을 사용한다`() {
        val response = MockHttpServletResponse()
        AuthController(sessions("none"), mock(JdbcTemplate::class.java), mock(RedisLimits::class.java)).logout(response)
        val header = requireNotNull(response.getHeader("Set-Cookie")).lowercase()
        assertTrue(header.contains("samesite=none"))
        assertTrue(header.contains("secure"))
        assertTrue(header.contains("httponly"))
        assertTrue(header.contains("path=/"))
        assertTrue(header.contains("max-age=0"))
    }
}
