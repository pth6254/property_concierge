package kr.propertyconcierge.core

import org.springframework.http.ResponseEntity
import org.springframework.web.bind.annotation.ExceptionHandler
import org.springframework.web.bind.annotation.RestControllerAdvice
import org.springframework.web.bind.MethodArgumentNotValidException
import org.springframework.http.converter.HttpMessageNotReadableException

class ApiFailure(val status: Int, override val message: String, val retryAfter: Long? = null) : RuntimeException(message)

@RestControllerAdvice
class ApiFailureHandler {
    @ExceptionHandler(org.springframework.dao.DataAccessException::class)
    fun storage(error: Exception): ResponseEntity<Map<String, String>> {
        org.slf4j.LoggerFactory.getLogger(javaClass).error("저장 실패 유형: {}", error.javaClass.simpleName)
        return ResponseEntity.status(503).body(mapOf("detail" to "저장소 요청을 완료하지 못했습니다. 잠시 후 다시 시도해주세요"))
    }
    @ExceptionHandler(ApiFailure::class)
    fun expected(error: ApiFailure): ResponseEntity<Map<String, String>> {
        val response = ResponseEntity.status(error.status)
        error.retryAfter?.let { response.header("Retry-After", it.toString()) }
        return response.body(mapOf("detail" to error.message))
    }

    @ExceptionHandler(MethodArgumentNotValidException::class, HttpMessageNotReadableException::class, IllegalArgumentException::class,
        com.fasterxml.jackson.core.JacksonException::class)
    fun invalid(error: Exception): ResponseEntity<Map<String, String>> {
        org.slf4j.LoggerFactory.getLogger(javaClass).warn("입력 거부 유형: {}", error.javaClass.simpleName)
        return ResponseEntity.unprocessableEntity().body(mapOf("detail" to "입력 값과 형식을 확인해주세요"))
    }
}
