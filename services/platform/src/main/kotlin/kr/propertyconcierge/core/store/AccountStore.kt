package kr.propertyconcierge.core.store

import com.fasterxml.jackson.databind.JsonNode
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.stereotype.Service
import org.springframework.transaction.support.TransactionTemplate
import kr.propertyconcierge.core.ApiFailure
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

@Service
class AccountStore(private val jdbc: JdbcTemplate, private val tx: TransactionTemplate) {
    private fun user(column: String, value: Any): Map<String, Any?>? = jdbc.queryForList(
        "SELECT id,email,password_hash,name,avatar_url,provider,provider_id,created,password_changed_at FROM users WHERE $column=?", value).firstOrNull()
    private fun text(args: JsonNode, key: String, fallback: String = "") = args.get(key)?.takeUnless(JsonNode::isNull)?.asText() ?: fallback
    fun dispatch(operation: String, args: JsonNode): Any? = tx.execute<Any?> {
        val id = args.path("user_id").asLong()
        when (operation) {
            "get_by_email" -> user("email", text(args, "email"))
            "get_by_id" -> user("id", id)
            "create_local_user", "get_or_create_oauth_user" -> {
                val email = text(args, "email")
                val local = operation == "create_local_user"
                if (email.isBlank()) throw ApiFailure(422, "이메일이 필요합니다")
                val created = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"))
                if (local) {
                    val newId = jdbc.queryForObject("""INSERT INTO users(email,password_hash,name,avatar_url,provider,created)
                        VALUES (?,?,?,'','local',?) RETURNING id""", Long::class.java, email, text(args, "password_hash"), text(args, "name"), created)
                    user("id", requireNotNull(newId))
                } else {
                    // OAuth 동시 콜백도 이메일 유일성 제약 안에서 동일 계정으로 합친다.
                    val newId = jdbc.queryForObject("""INSERT INTO users(email,name,avatar_url,provider,provider_id,created)
                        VALUES (?,?,?,?,?,?) ON CONFLICT(email) DO UPDATE SET name=excluded.name,avatar_url=excluded.avatar_url,
                        provider=excluded.provider,provider_id=excluded.provider_id RETURNING id""", Long::class.java,
                        email, text(args, "name"), text(args, "avatar_url"), text(args, "provider"), text(args, "provider_id"), created)
                    user("id", requireNotNull(newId))
                }
            }
            "update_password" -> {
                if (user("id", id) == null) return@execute null
                jdbc.update("UPDATE users SET password_hash=?,password_changed_at=? WHERE id=?", text(args, "password_hash"),
                    LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss.SSSSSS")), id)
                user("id", id)
            }
            "delete_user" -> { jdbc.update("DELETE FROM users WHERE id=?", id); null }
            else -> throw ApiFailure(404, "회원 저장 경로가 없습니다")
        }
    }
}
