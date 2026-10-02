package kr.propertyconcierge.core.integration

import org.testcontainers.containers.GenericContainer
import org.testcontainers.containers.Network
import org.testcontainers.containers.PostgreSQLContainer
import org.testcontainers.containers.startupcheck.OneShotStartupCheckStrategy
import org.testcontainers.utility.DockerImageName
import java.time.Duration
import java.util.UUID

private class TestPostgres : PostgreSQLContainer<TestPostgres>(
    DockerImageName.parse("pgvector/pgvector:pg16").asCompatibleSubstituteFor("postgres"))
private class TestService(image: String) : GenericContainer<TestService>(DockerImageName.parse(image))

/** 접속 환경변수를 상속하지 않고, 이번 JVM이 생성한 저장소만 테스트에 제공한다. */
object PlatformTestRuntime {
    private val isolatedNetwork = Network.newNetwork()
    private val isolatedPassword = UUID.randomUUID().toString()
    private val postgres = TestPostgres().apply {
        withDatabaseName("real_estate_test"); withUsername("platform_test"); withPassword(isolatedPassword)
        withNetwork(isolatedNetwork); withNetworkAliases("platform-test-db")
        withLabel("kr.propertyconcierge.test", "platform")
    }
    private val redis = TestService("redis:7-alpine").apply {
        withExposedPorts(6379); withNetwork(isolatedNetwork); withNetworkAliases("platform-test-redis")
        withLabel("kr.propertyconcierge.test", "platform")
    }
    val databaseUrl: String
    val redisUrl: String
    val jdbcUrl: String

    init {
        try {
            postgres.start(); redis.start()
            // Alembic을 스키마의 단일 원본으로 유지한다. Python API나 pytest는 실행하지 않는다.
            TestService(System.getenv("PLATFORM_MIGRATION_IMAGE") ?: "property_concierge_backend:latest").use { migration ->
                migration.withNetwork(isolatedNetwork)
                    .withEnv("DATABASE_URL", "postgresql://platform_test:$isolatedPassword@platform-test-db:5432/real_estate_test")
                    .withEnv("REDIS_URL", "redis://platform-test-redis:6379/15")
                    .withCommand("alembic", "-c", "services/intelligence/alembic.ini", "upgrade", "head")
                    .withStartupCheckStrategy(OneShotStartupCheckStrategy().withTimeout(Duration.ofSeconds(90)))
                    .withLabel("kr.propertyconcierge.test", "platform")
                migration.start()
                check(migration.currentContainerInfo.state.exitCodeLong == 0L) { "테스트 스키마 마이그레이션 실패" }
            }
            databaseUrl = "postgresql://platform_test:$isolatedPassword@${postgres.host}:${postgres.getMappedPort(5432)}/real_estate_test"
            redisUrl = "redis://${redis.host}:${redis.getMappedPort(6379)}/15"
            jdbcUrl = postgres.jdbcUrl
            Runtime.getRuntime().addShutdownHook(Thread { close() })
        } catch (error: Exception) {
            close(); throw IllegalStateException("Kotlin 전용 테스트 저장소를 준비하지 못했습니다", error)
        }
    }
    private fun close() {
        runCatching { redis.stop() }; runCatching { postgres.stop() }; runCatching { isolatedNetwork.close() }
    }
}
