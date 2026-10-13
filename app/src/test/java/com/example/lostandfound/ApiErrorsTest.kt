package com.example.lostandfound

import com.example.lostandfound.net.ApiErrors
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ApiErrorsTest {
    @Test
    fun messageWrittenByTheServerIsShown() {
        assertEquals("You have too many open reports.", ApiErrors.message(429, """{"error":"You have too many open reports."}"""))
        assertEquals("Match not found", ApiErrors.message(404, """{"error":"Match not found"}"""))
    }

    @Test
    fun expiredLoginAsksToSignInAgain() {
        // API Gateway answers {"message":"Unauthorized"} before our code runs
        assertEquals("Please sign in again.", ApiErrors.message(401, """{"message":"Unauthorized"}"""))
    }

    @Test
    fun otherGatewayErrorsStayGeneric() {
        assertTrue(ApiErrors.message(429, """{"message":"Too Many Requests"}""").contains("wait"))
        assertEquals("Request failed (503).", ApiErrors.message(503, "<html>Service Unavailable</html>"))
    }
}
