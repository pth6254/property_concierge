package kr.propertyconcierge.core.auth

import com.fasterxml.jackson.module.kotlin.jacksonObjectMapper
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.mockito.Mockito.*
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.mock.env.MockEnvironment
import kr.propertyconcierge.core.ApiFailure
import java.time.Instant
import java.util.Base64
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

class SessionServiceTest {
    private val key = "spring-unit-test-secret-not-for-production"
    private val jdbc = mock(JdbcTemplate::class.java)
    private val env = MockEnvironment().withProperty("JWT_SECRET_KEY", key)
    private val json = jacksonObjectMapper()
    private fun service() = spy(SessionService(jdbc, json, env))
    private val user = CoreUser(42, "unit@example.com", "검증", "", "local", null, null)
    private fun legacyToken(claims: Map<String, Any>, algorithm: String = "HS256"): String {
        val encode = Base64.getUrlEncoder().withoutPadding()
        val body = encode.encodeToString(json.writeValueAsBytes(mapOf("alg" to algorithm, "typ" to "JWT"))) + "." +
            encode.encodeToString(json.writeValueAsBytes(claims))
        val signature = Mac.getInstance("HmacSHA256").run { init(SecretKeySpec(key.toByteArray(), "HmacSHA256")); doFinal(body.toByteArray()) }
        return body + "." + encode.encodeToString(signature)
    }
    @Test
    fun `기존 HS256 세션과 새 세션을 검증한다`() {
        val service = service(); doReturn(user).`when`(service).userById(42)
        assertEquals(user, service.validate(legacyToken(mapOf("sub" to "42", "exp" to Instant.now().epochSecond + 60))))
        assertEquals(user, service.validate(service.issue(user)))
    }
    @Test
    fun `비밀번호 변경 전 세션과 만료 변조 알고리즘을 거부한다`() {
        val service = service(); val changed = user.copy(passwordChangedAt = "2026-10-01T12:00:00+00:00")
        doReturn(changed).`when`(service).userById(42)
        val claims = mapOf("sub" to "42", "exp" to Instant.now().epochSecond + 60)
        assertThrows(ApiFailure::class.java) { service.validate(legacyToken(claims)) }
        assertThrows(ApiFailure::class.java) { service.validate(legacyToken(claims + ("exp" to 1))) }
        assertThrows(ApiFailure::class.java) { service.validate(legacyToken(claims, "none")) }
        assertThrows(ApiFailure::class.java) { service.validate(legacyToken(claims).dropLast(5) + "abcde") }
        assertEquals(changed, service.validate(service.issue(changed)))
    }
    @Test
    fun `쿠키 설정 오타는 기동 실패하고 none은 secure를 켠다`() {
        assertThrows(IllegalArgumentException::class.java) { SessionService(jdbc, json, env.withProperty("COOKIE_SAMESITE", "typo")) }
        assertTrue(SessionService(jdbc, json, env.withProperty("COOKIE_SAMESITE", "none")).secure)
    }
}
