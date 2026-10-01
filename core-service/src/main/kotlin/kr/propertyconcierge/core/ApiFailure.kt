package kr.propertyconcierge.core

import org.springframework.http.ResponseEntity
import org.springframework.web.bind.annotation.ExceptionHandler
import org.springframework.web.bind.annotation.RestControllerAdvice
import org.springframework.web.bind.MethodArgumentNotValidException
import org.springframework.http.converter.HttpMessageNotReadableException

class ApiFailure(val status: Int, override val message: String) : RuntimeException(message)

@RestControllerAdvice
class ApiFailureHandler {
    @ExceptionHandler(ApiFailure::class)
    fun expected(error: ApiFailure) = ResponseEntity.status(error.status).body(mapOf("detail" to error.message))

    @ExceptionHandler(MethodArgumentNotValidException::class, HttpMessageNotReadableException::class, IllegalArgumentException::class,
        com.fasterxml.jackson.core.JacksonException::class)
    fun invalid(error: Exception): ResponseEntity<Map<String, String>> {
        org.slf4j.LoggerFactory.getLogger(javaClass).warn("입력 거부 유형: {}", error.javaClass.simpleName)
        return ResponseEntity.unprocessableEntity().body(mapOf("detail" to "입력 값과 형식을 확인해주세요"))
    }
}
