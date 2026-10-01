package kr.propertyconcierge.core

import com.zaxxer.hikari.HikariDataSource
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.core.env.Environment
import java.net.URI
import java.net.URLDecoder
import java.nio.charset.StandardCharsets
import javax.sql.DataSource
import com.fasterxml.jackson.databind.DeserializationFeature
import com.fasterxml.jackson.databind.ObjectMapper
import com.fasterxml.jackson.databind.PropertyNamingStrategies
import com.fasterxml.jackson.module.kotlin.KotlinFeature
import com.fasterxml.jackson.module.kotlin.KotlinModule

@Configuration
class CoreConfiguration {
    @Bean
    fun objectMapper(): ObjectMapper = ObjectMapper()
        // JSON의 null이 0·false나 List<String>의 null 원소로 바뀌면 Kotlin 타입 보장이 무너진다.
        .registerModule(KotlinModule.Builder().enable(KotlinFeature.StrictNullChecks).build())
        .findAndRegisterModules()
        .setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE)
        .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, DeserializationFeature.FAIL_ON_NULL_FOR_PRIMITIVES)
        .disable(DeserializationFeature.ACCEPT_FLOAT_AS_INT)

    @Bean
    fun dataSource(env: Environment): DataSource {
        // 기존 PostgreSQL 스키마를 읽는다. Hibernate 자동 DDL이나 SQLite 대체 경로를 두지 않는다.
        val raw = env.getRequiredProperty("DATABASE_URL").replace("postgresql+psycopg2://", "postgresql://")
        val uri = URI(raw)
        require(uri.scheme == "postgresql" && uri.host != null && uri.path.length > 1) { "PostgreSQL DATABASE_URL이 필요합니다" }
        val credentials = requireNotNull(uri.rawUserInfo) { "DB 자격증명이 필요합니다" }.split(":", limit = 2)
        require(credentials.size == 2)
        return HikariDataSource().apply {
            jdbcUrl = "jdbc:postgresql://${uri.host}:${if (uri.port < 0) 5432 else uri.port}${uri.rawPath}" +
                (uri.rawQuery?.let { "?$it" } ?: "")
            // URI의 +는 공백이 아니다. form decoder의 동작 때문에 기존 비밀번호를 바꾸지 않는다.
            username = URLDecoder.decode(credentials[0].replace("+", "%2B"), StandardCharsets.UTF_8)
            password = URLDecoder.decode(credentials[1].replace("+", "%2B"), StandardCharsets.UTF_8)
            maximumPoolSize = 8
            connectionTimeout = 5000
        }
    }

    @Bean
    fun requiredRedisConfiguration(env: Environment): String {
        val uri = URI(env.getRequiredProperty("REDIS_URL"))
        require(uri.scheme in setOf("redis", "rediss") && uri.host != null) { "REDIS_URL이 필요합니다" }
        return "configured"
    }
}
