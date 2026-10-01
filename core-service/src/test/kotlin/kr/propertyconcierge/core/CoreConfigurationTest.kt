package kr.propertyconcierge.core

import com.zaxxer.hikari.HikariDataSource
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.springframework.mock.env.MockEnvironment

class CoreConfigurationTest {
    @Test
    fun `DB URI 비밀번호의 더하기와 인코딩된 기호를 보존한다`() {
        val env = MockEnvironment().withProperty("DATABASE_URL", "postgresql://operator:p+a%40ss@localhost:5432/real_estate_test")
        val source = CoreConfiguration().dataSource(env) as HikariDataSource
        source.use {
            assertEquals("p+a@ss", it.password)
            assertEquals("jdbc:postgresql://localhost:5432/real_estate_test", it.jdbcUrl)
        }
    }

    @Test
    fun `DB와 Redis 설정을 생략하거나 다른 저장소를 지정하면 기동을 거부한다`() {
        val configuration = CoreConfiguration()
        assertThrows(IllegalStateException::class.java) { configuration.dataSource(MockEnvironment()) }
        assertThrows(IllegalArgumentException::class.java) {
            configuration.dataSource(MockEnvironment().withProperty("DATABASE_URL", "sqlite:///test.db"))
        }
        assertThrows(IllegalStateException::class.java) { configuration.requiredRedisConfiguration(MockEnvironment()) }
        assertThrows(IllegalArgumentException::class.java) {
            configuration.requiredRedisConfiguration(MockEnvironment().withProperty("REDIS_URL", ""))
        }
    }
}
