package kr.propertyconcierge.core.auth

import kr.propertyconcierge.core.integrations.ExternalJsonClient
import org.springframework.core.env.Environment
import org.springframework.stereotype.Service

@Service
class PasswordResetMail(private val http: ExternalJsonClient, env: Environment) {
    private val key = env.getProperty("RESEND_API_KEY", "")
    private val from = env.getProperty("MAIL_FROM", "no-reply@localhost")
    private val endpoint = env.getProperty("RESEND_API_URL", "https://api.resend.com/emails")
    private val log = org.slf4j.LoggerFactory.getLogger(javaClass)
    fun send(email: String, link: String) {
        if (key.isBlank()) {
            // 도메인 인증 전의 로컬 복구 경로를 유지한다. 실제 메일 발송으로 설명하지 않는다.
            log.warn("[email] 발송 설정 없음 — 로컬 재설정 링크: {}", link)
            return
        }
        runCatching { http.post(endpoint, mapOf("Authorization" to "Bearer $key"), mapOf(
            "from" to from, "to" to listOf(email), "subject" to "[부동산 컨시어지] 비밀번호 재설정 안내",
            "html" to "<p>아래 링크에서 비밀번호를 재설정하세요. 30분간 유효합니다.</p><a href=\"$link\">비밀번호 재설정</a>")) }
            .onFailure { log.error("비밀번호 재설정 메일 발송 실패 유형: {}", it.javaClass.simpleName) }
    }
}
