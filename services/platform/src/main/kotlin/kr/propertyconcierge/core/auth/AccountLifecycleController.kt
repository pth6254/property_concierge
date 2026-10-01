package kr.propertyconcierge.core.auth

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import jakarta.servlet.http.HttpServletRequest
import jakarta.servlet.http.HttpServletResponse
import jakarta.validation.Valid
import jakarta.validation.constraints.Size
import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.integrations.ExternalJsonClient
import kr.propertyconcierge.core.store.AccountStore
import org.springframework.core.env.Environment
import org.springframework.data.redis.core.StringRedisTemplate
import org.springframework.http.ResponseCookie
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder
import org.springframework.web.bind.annotation.*
import java.security.MessageDigest
import java.security.SecureRandom
import java.time.Duration
import java.util.Base64

data class ResetEmailInput(@field:Size(max=255) val email: String)
data class ResetConfirmInput(@field:Size(min=1,max=200) val token: String, @field:Size(min=8,max=72) val newPassword: String)

@RestController
@RequestMapping("/api/auth")
class AccountLifecycleController(private val sessions: SessionService, private val accounts: AccountStore,
    private val limits: RedisLimits, private val redis: StringRedisTemplate, private val json: ObjectMapper,
    private val mail: PasswordResetMail, private val http: ExternalJsonClient, env: Environment) {
    private val clientId = env.getProperty("GOOGLE_CLIENT_ID", "")
    private val clientSecret = env.getProperty("GOOGLE_CLIENT_SECRET", "")
    private val redirectUri = env.getProperty("GOOGLE_REDIRECT_URI", "http://localhost:3002/api/auth/google/callback")
    private val frontend = env.getProperty("FRONTEND_URL", "http://localhost:3002").trimEnd('/')
    private val authorize = env.getProperty("GOOGLE_AUTH_URL", "https://accounts.google.com/o/oauth2/v2/auth")
    private val tokenUrl = env.getProperty("GOOGLE_TOKEN_URL", "https://oauth2.googleapis.com/token")
    private val userInfoUrl = env.getProperty("GOOGLE_USERINFO_URL", "https://www.googleapis.com/oauth2/v2/userinfo")
    private val passwords = BCryptPasswordEncoder(12)
    private fun random() = Base64.getUrlEncoder().withoutPadding().encodeToString(ByteArray(32).also { SecureRandom().nextBytes(it) })
    private fun args(values: Map<String, Any?>) = json.valueToTree<JsonNode>(values)
    private fun cookie(response: HttpServletResponse, name: String, value: String, age: Long) {
        response.addHeader("Set-Cookie", ResponseCookie.from(name, value).httpOnly(true).secure(sessions.secure)
            .sameSite(if (name == "oauth_state") "lax" else sessions.sameSite).path("/").maxAge(age).build().toString())
    }
    @PostMapping("/password-reset/request")
    fun requestReset(@Valid @RequestBody body: ResetEmailInput, request: HttpServletRequest): Map<String, Any> {
        limits.check("password-reset-request", request.remoteAddr, 3, 3600)
        val email = body.email.trim().lowercase()
        val user = sessions.userByEmail(email)
        if (user?.provider == "local" && user.passwordHash != null) {
            val token = random()
            redis.opsForValue().set("pwreset:$token", user.id.toString(), Duration.ofMinutes(30))
            mail.send(email, "$frontend/reset-password?token=$token")
        }
        return mapOf("ok" to true, "message" to "입력하신 이메일로 재설정 링크를 보냈습니다. 메일함을 확인해주세요.")
    }
    @PostMapping("/password-reset/confirm")
    fun confirm(@Valid @RequestBody body: ResetConfirmInput, request: HttpServletRequest, response: HttpServletResponse): Map<String, Any> {
        limits.check("password-reset-confirm", request.remoteAddr, 10, 3600)
        if(body.newPassword.toByteArray().size>72) throw ApiFailure(422,"비밀번호는 UTF-8 72바이트 이하여야 합니다")
        // GETDEL로 토큰을 선점해 동시 재설정도 한 번만 실행한다.
        val owner = redis.opsForValue().getAndDelete("pwreset:${body.token}")?.toLongOrNull()
            ?: throw ApiFailure(400, "링크가 만료되었거나 이미 사용되었습니다. 재설정을 다시 요청해주세요.")
        val updated = accounts.dispatch("update_password", args(mapOf("user_id" to owner, "password_hash" to passwords.encode(body.newPassword))))
            ?: throw ApiFailure(400, "사용자를 찾을 수 없습니다")
        limits.clear((updated as Map<*, *>)["email"].toString())
        cookie(response, "auth_token", "", 0)
        return mapOf("ok" to true, "message" to "비밀번호가 변경되었습니다. 새 비밀번호로 로그인해주세요.")
    }
    @GetMapping("/google")
    fun google(response: HttpServletResponse) {
        if (clientId.isBlank()) throw ApiFailure(501, "Google OAuth가 설정되지 않았습니다")
        val state = random(); val verifier = random()
        redis.opsForValue().set("oauth-state:$state", verifier, Duration.ofMinutes(10))
        cookie(response, "oauth_state", state, 600)
        val challenge = Base64.getUrlEncoder().withoutPadding().encodeToString(MessageDigest.getInstance("SHA-256").digest(verifier.toByteArray()))
        response.status = 302
        response.setHeader("Location", authorize + "?" + http.form(mapOf("client_id" to clientId, "redirect_uri" to redirectUri,
            "response_type" to "code", "scope" to "openid email profile", "access_type" to "offline", "state" to state,
            "code_challenge" to challenge, "code_challenge_method" to "S256")))
    }
    @GetMapping("/google/callback")
    fun callback(@RequestParam code: String, @RequestParam(required=false) state: String?, request: HttpServletRequest, response: HttpServletResponse) {
        if (clientId.isBlank()) throw ApiFailure(501, "Google OAuth가 설정되지 않았습니다")
        val bound = request.cookies?.firstOrNull { it.name == "oauth_state" }?.value
        if (state == null || state.length > 200 || bound == null || !MessageDigest.isEqual(state.toByteArray(), bound.toByteArray()))
            throw ApiFailure(400, "OAuth 요청을 다시 시작해주세요")
        val verifier = redis.opsForValue().getAndDelete("oauth-state:$state") ?: throw ApiFailure(400, "OAuth 요청이 만료되었습니다")
        val token = http.parse(http.text("POST", tokenUrl, mapOf("Content-Type" to "application/x-www-form-urlencoded"),
            http.form(mapOf("code" to code, "client_id" to clientId, "client_secret" to clientSecret, "redirect_uri" to redirectUri,
                "grant_type" to "authorization_code", "code_verifier" to verifier)))).path("access_token").asText()
        if (token.isBlank()) throw ApiFailure(502, "Google 인증 응답을 확인하지 못했습니다")
        val info = http.get(userInfoUrl, mapOf("Authorization" to "Bearer $token"))
        if (!info.path("verified_email").asBoolean(false) || info.path("email").asText().isBlank() || info.path("id").asText().isBlank())
            throw ApiFailure(502, "Google에서 확인한 이메일이 필요합니다")
        val saved = accounts.dispatch("get_or_create_oauth_user", args(mapOf("email" to info.path("email").asText().lowercase(),
            "name" to info.path("name").asText(""), "avatar_url" to info.path("picture").asText(""), "provider" to "google", "provider_id" to info.path("id").asText()))) as Map<*, *>
        val user = sessions.userById((saved["id"] as Number).toLong()) ?: throw ApiFailure(503, "인증 계정을 확인하지 못했습니다")
        cookie(response, "oauth_state", "", 0); cookie(response, "auth_token", sessions.issue(user), 604800)
        response.status = 302; response.setHeader("Location", frontend)
    }
    @DeleteMapping("/me")
    fun withdraw(request: HttpServletRequest, response: HttpServletResponse): Map<String, Boolean> {
        val owner = sessions.required(request).id
        accounts.dispatch("delete_user", args(mapOf("user_id" to owner)))
        // 순차 ID 접두사가 겹치지 않도록 구분자까지 지정해 해당 계정의 AI 맥락만 제거한다.
        for (prefix in listOf("law-chat:$owner:", "concierge:$owner:")) {
            redis.scan(org.springframework.data.redis.core.ScanOptions.scanOptions().match("$prefix*").count(100).build()).use { keys ->
                while (keys.hasNext()) redis.delete(keys.next())
            }
        }
        cookie(response, "auth_token", "", 0)
        return mapOf("ok" to true)
    }
}
