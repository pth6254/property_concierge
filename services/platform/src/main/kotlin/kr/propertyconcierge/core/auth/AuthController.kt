package kr.propertyconcierge.core.auth

import jakarta.servlet.http.HttpServletRequest
import jakarta.servlet.http.HttpServletResponse
import jakarta.validation.Valid
import jakarta.validation.constraints.NotBlank
import jakarta.validation.constraints.Email
import jakarta.validation.constraints.Size
import kr.propertyconcierge.core.ApiFailure
import org.springframework.dao.DuplicateKeyException
import org.springframework.http.ResponseCookie
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder
import org.springframework.transaction.annotation.Transactional
import org.springframework.web.bind.annotation.*
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

data class RegisterInput(@field:NotBlank @field:Email @field:Size(max=255) val email: String,
    @field:Size(min=8,max=72) val password: String, @field:Size(max=100) val name: String = "")
data class LoginInput(@field:NotBlank val email: String, @field:NotBlank @field:Size(max=72) val password: String)

@RestController
@RequestMapping("/api/auth")
class AuthController(private val sessions: SessionService, private val jdbc: JdbcTemplate, private val limits: RedisLimits) {
    private val passwords = BCryptPasswordEncoder(12)
    private fun cookie(response: HttpServletResponse, value: String, seconds: Long = 604800) {
        response.addHeader("Set-Cookie", ResponseCookie.from("auth_token", value).httpOnly(true).secure(sessions.secure)
            .sameSite(sessions.sameSite).path("/").maxAge(seconds).build().toString())
    }
    @PostMapping("/register")
    @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
    @Transactional
    fun register(@Valid @RequestBody body: RegisterInput, request: HttpServletRequest, response: HttpServletResponse): Map<String, Any> {
        limits.check("register", request.remoteAddr, 5, 60)
        if (body.password.toByteArray().size > 72) throw ApiFailure(422, "비밀번호는 UTF-8 72바이트 이하여야 합니다")
        val id = try { jdbc.queryForObject(
            "INSERT INTO users(email,password_hash,name,avatar_url,provider,created) VALUES (?,?,?,'','local',?) RETURNING id",
            Long::class.java, body.email, passwords.encode(body.password), body.name,
            LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"))) }
        catch (_: DuplicateKeyException) { throw ApiFailure(409, "이미 사용 중인 이메일입니다") }
        val user = requireNotNull(sessions.userById(requireNotNull(id)))
        cookie(response, sessions.issue(user))
        return sessions.view(user)
    }
    @PostMapping("/login")
    fun login(@Valid @RequestBody body: LoginInput, request: HttpServletRequest, response: HttpServletResponse): Map<String, Any> {
        limits.check("login", request.remoteAddr, 10, 60); limits.lock(body.email)
        val user = sessions.userByEmail(body.email)
        if (user?.passwordHash == null || !passwords.matches(body.password, user.passwordHash)) {
            limits.failed(body.email); throw ApiFailure(401, "이메일 또는 비밀번호가 올바르지 않습니다")
        }
        limits.clear(body.email); cookie(response, sessions.issue(user)); return sessions.view(user)
    }
    @GetMapping("/me")
    fun me(request: HttpServletRequest) = sessions.view(sessions.required(request))
    @PostMapping("/logout")
    fun logout(response: HttpServletResponse): Map<String, Boolean> { cookie(response, "", 0); return mapOf("ok" to true) }
}
