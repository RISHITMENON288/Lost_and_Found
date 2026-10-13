package com.example.lostandfound

import com.example.lostandfound.data.CognitoErrors
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CognitoErrorsTest {
    @Test
    fun wrongPasswordHasFriendlyMessage() {
        assertEquals("Incorrect email or password.", CognitoErrors.friendly("NotAuthorizedException", "Incorrect username or password."))
    }

    @Test
    fun domainRestrictionMessageIsPassedThrough() {
        val message = "PreSignUp failed with error Please sign up with your @campus.edu email address..".trim()
        assertEquals("Please sign up with your @campus.edu email address.", CognitoErrors.friendly("UserLambdaValidationException", message))
    }

    @Test
    fun unknownErrorsDoNotLeakRawText() {
        val text = CognitoErrors.friendly("SomethingInternalException", "arn:aws:secret-detail")
        assertTrue(!text.contains("arn:"))
    }

    @Test
    fun throttlingAsksToWait() {
        assertTrue(CognitoErrors.friendly("TooManyRequestsException", "").contains("wait"))
    }
}
