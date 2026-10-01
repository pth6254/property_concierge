package kr.propertyconcierge.core

import jakarta.servlet.http.HttpServletRequest
import jakarta.servlet.http.HttpServletResponse
import kr.propertyconcierge.core.bridge.TransitionController
import org.springframework.context.annotation.Configuration
import org.springframework.web.method.HandlerMethod
import org.springframework.web.servlet.HandlerInterceptor
import org.springframework.web.servlet.HandlerMapping
import org.springframework.web.servlet.config.annotation.InterceptorRegistry
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer

@Configuration
class CoreRequestMetrics(private val metrics: CoreUsageMetrics): WebMvcConfigurer {
    override fun addInterceptors(registry: InterceptorRegistry) {
        registry.addInterceptor(object: HandlerInterceptor {
            override fun preHandle(request: HttpServletRequest, response: HttpServletResponse, handler: Any): Boolean {
                if (request.getAttribute("core.metrics.started") == null)
                    request.setAttribute("core.metrics.started", System.nanoTime())
                return true
            }
            override fun afterCompletion(request: HttpServletRequest, response: HttpServletResponse, handler: Any, ex: Exception?) {
                // 중계 경로는 기존 Python이 집계한다. 중복 집계나 실제 URL·식별자 저장을 피한다.
                if (handler !is HandlerMethod || handler.beanType == TransitionController::class.java) return
                val template = request.getAttribute(HandlerMapping.BEST_MATCHING_PATTERN_ATTRIBUTE)?.toString() ?: return
                if (!template.startsWith("/api/") || template.startsWith("/api/operations")) return
                val started = request.getAttribute("core.metrics.started") as? Long ?: return
                metrics.request(request.method, template, (System.nanoTime()-started)/1_000_000_000.0, response.status)
            }
        })
    }
}
