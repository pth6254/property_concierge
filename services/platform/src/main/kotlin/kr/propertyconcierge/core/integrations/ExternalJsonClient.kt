package kr.propertyconcierge.core.integrations

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import kr.propertyconcierge.core.ApiFailure
import org.springframework.stereotype.Service
import java.net.URI
import java.net.URLDecoder
import java.net.URLEncoder
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.nio.charset.StandardCharsets.UTF_8
import java.time.Duration

// 공공데이터 키는 원문 또는 URL 인코딩 형식이다. 원문 '+'를 폼의 공백으로 해석하면 인증이 깨진다.
fun decodeDataGoKey(value: String): String = if ('%' in value) URLDecoder.decode(value.replace("+", "%2B"), UTF_8) else value

@Service
class ExternalJsonClient(private val json: ObjectMapper) {
    private val client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(4)).followRedirects(HttpClient.Redirect.NEVER).build()
    fun encoded(value: String) = URLEncoder.encode(value, UTF_8)
    fun form(values: Map<String, String>) = values.entries.joinToString("&") { encoded(it.key) + "=" + encoded(it.value) }
    fun text(method: String, url: String, headers: Map<String, String> = emptyMap(), body: String? = null): String {
        val uri = URI(url)
        require(uri.scheme in setOf("http", "https") && uri.host != null && uri.userInfo == null)
        val request = HttpRequest.newBuilder(uri).timeout(Duration.ofSeconds(10))
        headers.forEach { (name, value) -> request.header(name, value) }
        request.method(method, body?.let(HttpRequest.BodyPublishers::ofString) ?: HttpRequest.BodyPublishers.noBody())
        try {
            val result = client.send(request.build(), HttpResponse.BodyHandlers.ofString(UTF_8))
            if (result.statusCode() !in 200..299 || result.body().length > 2_000_000) throw ApiFailure(502, "외부 정보 조회를 완료하지 못했습니다")
            return result.body()
        } catch (_: java.io.IOException) { throw ApiFailure(502, "외부 정보 조회에 연결하지 못했습니다") }
        catch (_: InterruptedException) { Thread.currentThread().interrupt(); throw ApiFailure(503, "외부 정보 조회가 중단되었습니다") }
    }
    fun get(url: String, headers: Map<String, String> = emptyMap()): JsonNode = parse(text("GET", url, headers))
    fun post(url: String, headers: Map<String, String>, data: Any): JsonNode = parse(text("POST", url,
        headers + ("Content-Type" to "application/json"), json.writeValueAsString(data)))
    fun parse(value: String): JsonNode = try { json.readTree(value) } catch (_: com.fasterxml.jackson.core.JacksonException) {
        throw ApiFailure(502, "외부 정보 응답 형식을 확인하지 못했습니다")
    }
}
