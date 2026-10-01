package kr.propertyconcierge.core.bridge

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import kr.propertyconcierge.core.ApiFailure
import org.springframework.core.env.Environment
import org.springframework.stereotype.Service
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration

data class PythonReply(val status: Int, val headers: Map<String, List<String>>, val body: ByteArray)

@Service
class PythonClient(env: Environment, private val json: ObjectMapper) {
    private val root = env.getRequiredProperty("PYTHON_AI_URL").trimEnd('/').also {
        require(URI(it).scheme in setOf("http", "https") && URI(it).host != null) { "PYTHON_AI_URL의 호스트 형식이 올바르지 않습니다" }
    }
    private val secret = env.getRequiredProperty("INTERNAL_SERVICE_SECRET").also { require(it.length >= 32) }
    private val client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).followRedirects(HttpClient.Redirect.NEVER).build()

    fun send(method: String, path: String, body: ByteArray = byteArrayOf(), cookie: String? = null, contentType: String? = null, clientIp: String? = null,
        timeoutSeconds: Long = 180): PythonReply {
        require(path.startsWith("/api/") || path.startsWith("/internal/v1/") || path == "/ready")
        require(!path.contains('\r') && !path.contains('\n'))
        val request = HttpRequest.newBuilder(URI(root + path)).timeout(Duration.ofSeconds(timeoutSeconds))
            .header("X-Internal-Service-Key", secret).header("Accept", "application/json")
        cookie?.let { request.header("Cookie", it) }
        contentType?.let { request.header("Content-Type", it) }
        clientIp?.let { request.header("X-Forwarded-For", it) }
        request.method(method, if (body.isEmpty()) HttpRequest.BodyPublishers.noBody() else HttpRequest.BodyPublishers.ofByteArray(body))
        try {
            val response = client.send(request.build(), HttpResponse.BodyHandlers.ofByteArray())
            return PythonReply(response.statusCode(), response.headers().map(), response.body())
        } catch (_: java.io.IOException) { throw ApiFailure(503, "분석 서비스에 연결하지 못했습니다. 잠시 후 다시 시도해주세요") }
    }
    fun analyze(path: String, data: Any): JsonNode {
        val result = send("POST", "/internal/v1/$path", json.writeValueAsBytes(data), contentType="application/json")
        if (result.status !in 200..299) {
            val detail = runCatching { json.readTree(result.body).path("detail").asText() }.getOrNull()
            throw ApiFailure(result.status, detail?.takeIf { it.isNotBlank() } ?: "분석 요청을 처리하지 못했습니다")
        }
        return json.readTree(result.body)
    }
}
