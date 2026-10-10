package kr.propertyconcierge.core.integration

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import jakarta.servlet.http.Cookie
import kr.propertyconcierge.core.bridge.PythonClient
import kr.propertyconcierge.core.auth.PasswordResetMail
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Assertions.*
import org.mockito.Mockito.doAnswer
import org.mockito.ArgumentMatchers.any
import org.mockito.ArgumentMatchers.anyString
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory
import org.springframework.data.redis.core.StringRedisTemplate
import org.springframework.http.MediaType
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.test.context.DynamicPropertyRegistry
import org.springframework.test.context.DynamicPropertySource
import org.springframework.test.context.bean.override.mockito.MockitoBean
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.MvcResult
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*
import org.springframework.transaction.support.TransactionSynchronizationManager
import java.time.Instant
import java.net.URI
import java.util.UUID

@SpringBootTest
@AutoConfigureMockMvc
abstract class PlatformIntegrationSupport {
    companion object {
        @JvmStatic @DynamicPropertySource
        fun properties(values: DynamicPropertyRegistry) {
            values.add("DATABASE_URL") { PlatformTestRuntime.databaseUrl }
            values.add("REDIS_URL") { PlatformTestRuntime.redisUrl }
            values.add("JWT_SECRET_KEY") { "kotlin-integration-only-not-a-service-secret" }
            values.add("INTERNAL_SERVICE_SECRET") { "kotlin-integration-only-internal-service-key" }
            values.add("PYTHON_AI_URL") { "http://127.0.0.1:1" }
            values.add("APP_ENV") { "development" }; values.add("COOKIE_SAMESITE") { "lax" }
            values.add("DISABLE_RATE_LIMIT") { "1" }; values.add("RESEND_API_KEY") { "" }
        }
    }
    @Autowired lateinit var mvc: MockMvc
    @Autowired lateinit var json: ObjectMapper
    @Autowired lateinit var jdbc: JdbcTemplate
    @Autowired lateinit var redis: StringRedisTemplate
    @MockitoBean lateinit var python: PythonClient
    @MockitoBean lateinit var mail: PasswordResetMail
    protected var validatedRows: List<JsonNode> = emptyList()
    protected var tradesFailure = false
    protected var duringReport: (() -> Unit)? = null

    @BeforeEach
    fun isolate() {
        jdbc.dataSource?.connection.use { connection ->
            requireNotNull(connection)
            // JDBC 드라이버가 연결 옵션을 정규화해도 호스트·포트·DB는 생성한 저장소와 같아야 한다.
            check(connection.metaData.url.substringBefore('?') == PlatformTestRuntime.jdbcUrl.substringBefore('?') &&
                connection.metaData.userName == "platform_test") { "테스트가 생성한 DB 연결만 허용합니다" }
        }
        check(jdbc.queryForObject("SELECT current_database()", String::class.java) == "real_estate_test")
        val factory = redis.connectionFactory as LettuceConnectionFactory
        val redisAddress = URI(PlatformTestRuntime.redisUrl)
        check(factory.database == 15 && redisAddress.path == "/15" &&
            factory.hostName == redisAddress.host && factory.port == redisAddress.port)
        jdbc.execute("TRUNCATE users,legal_regions RESTART IDENTITY CASCADE")
        factory.connection.use { it.serverCommands().flushDb() }
        validatedRows = emptyList(); duringReport = null; tradesFailure = false
        // 모의하는 것은 외부 분석 경계뿐이다. 회원·저장·권한·수식·트랜잭션은 실제 Spring이다.
        doAnswer { invocation ->
            check(!TransactionSynchronizationManager.isActualTransactionActive()) { "분석 호출은 DB 트랜잭션 밖이어야 합니다" }
            val path = invocation.getArgument<String>(0)
            val data = json.valueToTree<JsonNode>(invocation.getArgument<Any>(1))
            when (path) {
                "listing-import/validate" -> json.valueToTree<JsonNode>(mapOf("rows" to validatedRows,
                    "validation" to mapOf("valid" to true, "committed" to false, "total" to validatedRows.size,
                        "created" to 0, "updated" to 0, "unchanged" to 0, "skipped_older" to 0, "errors" to emptyList<String>(),
                        "warnings" to emptyList<String>(), "preview" to validatedRows.map { it.path("payload") })))
                "decision/decorate" -> data.path("snapshot").path("case").deepCopy<com.fasterxml.jackson.databind.node.ObjectNode>().apply {
                    set<JsonNode>("properties", json.valueToTree(data.path("snapshot").path("properties").map { it.path("property") }))
                }
                "data/listing-trades" -> {
                    if (tradesFailure) throw kr.propertyconcierge.core.ApiFailure(503, "분석 서비스에 연결하지 못했습니다")
                    json.valueToTree<JsonNode>(mapOf("available" to true, "echo" to data, "complex_name" to "확인 후보", "match" to "exact",
                        "trades" to listOf(mapOf("deal_date" to Instant.now().minusSeconds(86400L * 20).toString().take(10), "floor" to "5",
                            "area_sqm" to 84.9, "price_won" to 1_000_000_000L, "price_per_sqm_won" to 11_778_563L))))
                }
                "simulation/report" -> { duringReport?.invoke(); json.readTree("""{"report":"표현 경계 대역","report_output":{}}""") }
                else -> throw AssertionError("등록하지 않은 외부 분석 경계: $path")
            }
        }.`when`(python).analyze(anyString(), any(Any::class.java) ?: Any())
        seedRegions()
    }
    private fun seedRegions() {
        listOf(Triple("1100000000", "sido", "서울특별시"), Triple("1168000000", "sigungu", "서울특별시 강남구"),
            Triple("1168010100", "eup_myeon_dong", "서울특별시 강남구 역삼동")).forEachIndexed { index, (code, level, name) ->
            jdbc.update("""INSERT INTO legal_regions(code,sido_code,sigungu_code,eup_myeon_dong_code,ri_code,name,full_name,
                level,depth,resident_code,cadastral_code,sort_order,remarks,is_active,synced_at)
                VALUES (?, '11','680','101','00',?,?,?,?,'','',0,'',true,?)""", code, name.substringAfterLast(' '), name, level, index+1, Instant.now().epochSecond.toDouble())
        }
    }
    protected fun body(result: MvcResult): JsonNode = json.readTree(result.response.contentAsByteArray)
    protected fun request(method: String, path: String, input: Any? = null, cookie: Cookie? = null, expected: Int = 200): MvcResult {
        val builder = when(method) { "GET" -> get(path); "POST" -> post(path); "PATCH" -> patch(path); "DELETE" -> delete(path); else -> error("HTTP 방식 오류") }
        cookie?.let { builder.cookie(it) }
        input?.let { builder.contentType(MediaType.APPLICATION_JSON).content(json.writeValueAsBytes(it)) }
        val result = mvc.perform(builder).andReturn()
        assertEquals(expected, result.response.status, result.response.contentAsString)
        return result
    }
    protected fun register(email: String = "${UUID.randomUUID()}@example.com"): Pair<Long, Cookie> {
        val response = request("POST", "/api/auth/register", mapOf("email" to email, "password" to "native-test-password-123!", "name" to "Kotlin 검증"), expected=201)
        return body(response).path("id").asLong() to requireNotNull(response.response.getCookie("auth_token"))
    }
    protected fun case(cookie: Cookie, fields: Map<String, Any?> = emptyMap()): Long =
        body(request("POST", "/api/cases", mapOf("title" to "직접 검토") + fields, cookie, 201)).path("id").asLong()
    protected fun candidate(cookie: Cookie, caseId: Long, fields: Map<String, Any?> = emptyMap()): Long =
        body(request("POST", "/api/cases/$caseId/properties", mapOf("name" to "직접 후보", "asking_price" to 800_000_000L,
            "address" to "서울특별시 강남구 역삼동 123", "area_sqm" to 84.9, "category" to "아파트") + fields, cookie, 201)).path("id").asLong()
    protected fun row(id: String = "ad-1", price: Long = 800_000_000, status: String = "active", time: Instant = Instant.now(), unit: String = "501"): JsonNode =
        // 실제 Python REST 응답과 같은 JSON 숫자 노드로 만들어 메모리 타입 차이를 검증에 섞지 않는다.
        json.readTree(json.writeValueAsBytes(mapOf("row" to 2, "confirmed_at" to time.epochSecond.toDouble(), "price" to price,
            "payload" to mapOf("external_id" to id, "name" to "확인 후보", "alias" to "임장", "address" to "서울특별시 강남구 역삼동 123",
                "area_sqm" to 84.9, "property_type" to "apartment", "transaction_type" to "purchase", "status" to status,
                "legal_region_code" to "1168010100", "asking_price" to price, "confirmed_at" to time.toString(), "building_dong" to "101동",
                "unit_number" to unit, "floor" to "5층", "area_basis" to "exclusive"))))
    protected fun import(cookie: Cookie, rows: List<JsonNode>, expected: Int = 200): JsonNode {
        validatedRows = rows
        return body(request("POST", "/api/listings/import", mapOf("source_name" to "Kotlin 저장 검증", "csv_text" to "분석 경계 대역", "commit" to true), cookie, expected))
    }
    protected fun count(table: String): Long = requireNotNull(jdbc.queryForObject("SELECT count(*) FROM $table", Long::class.java))
}
