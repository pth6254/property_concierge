package kr.propertyconcierge.core.auth

import com.fasterxml.jackson.databind.ObjectMapper
import jakarta.servlet.http.HttpServletRequest
import kr.propertyconcierge.core.ApiFailure
import org.springframework.core.env.Environment
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.stereotype.Service
import java.nio.charset.StandardCharsets.UTF_8
import java.security.MessageDigest
import java.time.Instant
import java.util.Base64
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

data class CoreUser(val id: Long, val email: String, val name: String, val avatarUrl: String,
    val provider: String, val passwordHash: String?, val passwordChangedAt: String?)

@Service
class SessionService(private val jdbc: JdbcTemplate, private val json: ObjectMapper, env: Environment) {
    private val secret = env.getRequiredProperty("JWT_SECRET_KEY").also { require(it.isNotBlank()) }
    private val operators = env.getProperty("OPERATOR_USER_IDS", "").split(',').map(String::trim).toSet()
    val sameSite = env.getProperty("COOKIE_SAMESITE", "lax").trim().lowercase().also {
        require(it in setOf("lax", "strict", "none")) { "COOKIE_SAMESITE 설정이 올바르지 않습니다" }
    }
    val secure = env.getProperty("APP_ENV", "development") == "production" || sameSite == "none"

    fun userById(id: Long): CoreUser? = user("id", id)
    fun userByEmail(email: String): CoreUser? = user("email", email)
    private fun user(column: String, value: Any): CoreUser? = jdbc.query(
        "SELECT id,email,name,avatar_url,provider,password_hash,password_changed_at FROM users WHERE $column = ?",
        { rs, _ -> CoreUser(rs.getLong("id"), rs.getString("email"), rs.getString("name") ?: "",
            rs.getString("avatar_url") ?: "", rs.getString("provider") ?: "local", rs.getString("password_hash"),
            rs.getString("password_changed_at")) }, value).firstOrNull()

    fun operator(user: CoreUser) = user.id.toString() in operators
    fun view(user: CoreUser) = mapOf("id" to user.id, "email" to user.email, "name" to user.name,
        "avatar_url" to user.avatarUrl, "provider" to user.provider, "is_operator" to operator(user))

    private fun encode(bytes: ByteArray) = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)
    private fun signature(body: String): ByteArray = Mac.getInstance("HmacSHA256").run {
        init(SecretKeySpec(secret.toByteArray(UTF_8), "HmacSHA256")); doFinal(body.toByteArray(UTF_8))
    }
    fun issue(user: CoreUser): String {
        val claims = mutableMapOf<String, Any>("sub" to user.id.toString(), "exp" to Instant.now().epochSecond + 604800)
        user.passwordChangedAt?.let { claims["pwd_at"] = it }
        val body = encode(json.writeValueAsBytes(mapOf("alg" to "HS256", "typ" to "JWT"))) + "." + encode(json.writeValueAsBytes(claims))
        return body + "." + encode(signature(body))
    }
    fun validate(token: String): CoreUser {
        try {
            val parts = token.split('.')
            require(parts.size == 3 && token.length <= 8192)
            val decoder = Base64.getUrlDecoder()
            require(json.readTree(decoder.decode(parts[0])).path("alg").asText() == "HS256")
            require(MessageDigest.isEqual(signature(parts[0] + "." + parts[1]), decoder.decode(parts[2])))
            val claims = json.readTree(decoder.decode(parts[1]))
            require(claims.path("exp").isNumber && claims.path("exp").asLong() > Instant.now().epochSecond)
            for (claim in listOf("nbf", "iat")) if (claims.has(claim))
                require(claims.path(claim).isNumber && claims.path(claim).asDouble() <= Instant.now().epochSecond)
            val user = userById(claims.path("sub").asText().toLong()) ?: throw IllegalArgumentException()
            require(user.passwordChangedAt == null || claims.path("pwd_at").asText() == user.passwordChangedAt)
            return user
        } catch (_: IllegalArgumentException) { throw ApiFailure(401, "유효하지 않거나 만료된 로그인입니다") }
        catch (_: com.fasterxml.jackson.core.JacksonException) { throw ApiFailure(401, "유효하지 않은 로그인입니다") }
    }
    fun optional(request: HttpServletRequest): CoreUser? = request.cookies?.firstOrNull { it.name == "auth_token" }
        ?.let { validate(it.value) }
    fun required(request: HttpServletRequest) = optional(request) ?: throw ApiFailure(401, "로그인이 필요합니다")
}
