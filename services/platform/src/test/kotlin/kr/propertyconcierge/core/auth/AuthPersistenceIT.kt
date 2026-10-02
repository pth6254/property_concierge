package kr.propertyconcierge.core.auth

import kr.propertyconcierge.core.integration.PlatformIntegrationSupport
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.mockito.Mockito.verify
import org.mockito.ArgumentMatchers.eq
import org.mockito.ArgumentMatchers.contains

class AuthPersistenceIT : PlatformIntegrationSupport() {
    @Test fun `회원 가입 로그인 중복 가입과 로그아웃 쿠키를 검증한다`() {
        val (id, cookie) = register("native@example.com")
        assertEquals(id, body(request("GET", "/api/auth/me", cookie=cookie)).path("id").asLong())
        assertEquals(1L, count("users"))
        request("POST", "/api/auth/register", mapOf("email" to "native@example.com", "password" to "native-test-password-123!"), expected=409)
        val password = jdbc.queryForObject("SELECT password_hash FROM users WHERE id=?", String::class.java, id)
        assertNotEquals("native-test-password-123!", password)
        request("POST", "/api/auth/login", mapOf("email" to "native@example.com", "password" to "wrong-password"), expected=401)
        val login = request("POST", "/api/auth/login", mapOf("email" to "native@example.com", "password" to "native-test-password-123!"))
        assertNotNull(login.response.getCookie("auth_token"))
        val logout = request("POST", "/api/auth/logout", cookie=cookie)
        assertTrue(logout.response.getHeader("Set-Cookie").orEmpty().contains("Max-Age=0"))
    }
    @Test fun `재설정은 계정 존재를 노출하지 않고 이전 세션과 사용한 토큰을 폐기한다`() {
        val (id, cookie) = register("reset-native@example.com")
        val existing = body(request("POST", "/api/auth/password-reset/request", mapOf("email" to "reset-native@example.com")))
        val missing = body(request("POST", "/api/auth/password-reset/request", mapOf("email" to "missing@example.com")))
        assertEquals(existing, missing)
        val keys = redis.keys("pwreset:*"); assertEquals(1, keys.size)
        val token = keys.single().removePrefix("pwreset:")
        verify(mail).send(eq("reset-native@example.com") ?: "", contains("token=$token") ?: "")
        request("POST", "/api/auth/password-reset/confirm", mapOf("token" to token, "new_password" to "changed-password-456!"))
        assertNotNull(jdbc.queryForObject("SELECT password_changed_at FROM users WHERE id=?", String::class.java, id))
        request("GET", "/api/auth/me", cookie=cookie, expected=401)
        // 선택 인증 경로도 이전 쿠키를 익명 요청으로 바꿔 통과시키면 안 된다.
        request("POST", "/api/simulation", mapOf("purchase_price" to 800_000_000), cookie, 401)
        request("POST", "/api/auth/password-reset/confirm", mapOf("token" to token, "new_password" to "another-password-456!"), expected=400)
        request("POST", "/api/auth/login", mapOf("email" to "reset-native@example.com", "password" to "changed-password-456!"))
    }
    @Test fun `탈퇴는 본인 자료와 맥락만 제거하고 다른 계정을 보존한다`() {
        val (owner, cookie) = register(); val (other, otherCookie) = register()
        case(cookie); case(otherCookie)
        redis.opsForValue().set("concierge:$owner:session", "mine")
        redis.opsForValue().set("concierge:$other:session", "other")
        request("DELETE", "/api/auth/me", cookie=cookie)
        assertEquals(1L, count("users")); assertEquals(1L, count("purchase_cases"))
        assertNull(redis.opsForValue().get("concierge:$owner:session"))
        assertEquals("other", redis.opsForValue().get("concierge:$other:session"))
        request("GET", "/api/auth/me", cookie=cookie, expected=401)
        assertEquals(other, body(request("GET", "/api/auth/me", cookie=otherCookie)).path("id").asLong())
    }
}
