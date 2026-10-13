package com.example.lostandfound

import com.example.lostandfound.data.SupabaseErrors
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SupabaseErrorsTest {
    @Test
    fun wrongPasswordHasFriendlyMessage() {
        assertEquals("Incorrect email or password.", SupabaseErrors.friendly("invalid_credentials", 400))
    }

    @Test
    fun duplicateAccountSuggestsSigningIn() {
        assertTrue(SupabaseErrors.friendly("user_already_exists", 422).contains("sign"))
        assertTrue(SupabaseErrors.friendly("email_exists", 422).contains("sign"))
    }

    @Test
    fun wrongOrExpiredCodeIsExplained() {
        assertTrue(SupabaseErrors.friendly("otp_expired", 403).contains("code"))
    }

    @Test
    fun unknownErrorsDoNotLeakRawText() {
        val text = SupabaseErrors.friendly("some_internal_failure_code", 500)
        assertEquals("Something went wrong. Please try again.", text)
    }

    @Test
    fun throttlingAsksToWait() {
        assertTrue(SupabaseErrors.friendly("over_email_send_rate_limit", 429).contains("wait"))
        assertTrue(SupabaseErrors.friendly("", 429).contains("wait"))
    }
}
