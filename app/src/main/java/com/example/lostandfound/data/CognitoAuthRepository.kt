package com.example.lostandfound.data

import android.util.Base64
import com.example.lostandfound.net.Http
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONArray
import org.json.JSONObject

class CognitoException(val type: String, message: String) : Exception(message)

/** Maps Cognito error codes to messages a student can act on. Pure, so it is unit-tested. */
object CognitoErrors {
    fun friendly(type: String, message: String): String = when (type) {
        "NotAuthorizedException" -> "Incorrect email or password."
        "UsernameExistsException" -> "An account with this email already exists. Try signing in."
        "InvalidPasswordException" -> "Password needs 8+ characters with upper-case, lower-case and a number."
        "CodeMismatchException" -> "That code is not correct."
        "ExpiredCodeException" -> "That code has expired. Request a new one."
        "UserNotConfirmedException" -> "Please verify your email first."
        "LimitExceededException", "TooManyRequestsException", "TooManyFailedAttemptsException" ->
            "Too many attempts. Please wait a minute and try again."
        "UserLambdaValidationException" -> {
            val reason = message.substringAfter("failed with error ", "").trim().trimEnd('.')
            if (reason.isBlank()) "Sign-up is not allowed for this email." else "$reason."
        }
        "InvalidParameterException" -> "Please check the details you entered."
        else -> "Something went wrong. Please try again."
    }
}

/**
 * Talks to Amazon Cognito's public API over HTTPS (SignUp, ConfirmSignUp, InitiateAuth).
 * The app client has no secret; the password only travels over TLS to Cognito.
 * Tokens are kept in memory only, so a process restart means signing in again.
 *
 * [accessToken] returns the Cognito ID token (not the access token): API Gateway's JWT authorizer checks that
 * the token's audience is this app client, and only the ID token carries that.
 * The phone number is saved as Cognito's standard phone_number attribute; it is never SMS-verified.
 */
class CognitoAuthRepository(
    region: String,
    private val clientId: String
) : AuthRepository {
    private val endpoint = "https://cognito-idp.$region.amazonaws.com/"

    private var cachedIdToken: String? = null
    private var refreshToken: String? = null
    private var expiresAtMs = 0L
    private val lock = Mutex()

    private suspend fun call(target: String, body: JSONObject): JSONObject {
        val response = Http.request(
            method = "POST",
            url = endpoint,
            headers = mapOf(
                "Content-Type" to "application/x-amz-json-1.1",
                "X-Amz-Target" to "AWSCognitoIdentityProviderService.$target"
            ),
            body = body.toString().toByteArray(Charsets.UTF_8)
        )
        if (response.code == 200) return JSONObject(response.text)
        val json = try {
            JSONObject(response.text)
        } catch (_: Exception) {
            null
        }
        val type = json?.optString("__type").orEmpty().substringAfterLast('#')
        throw CognitoException(type, CognitoErrors.friendly(type, json?.optString("message").orEmpty()))
    }

    private inline fun <T> attempt(block: () -> T): Result<T> = try {
        Result.success(block())
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        Result.failure(e)
    }

    private fun normalize(email: String) = email.trim().lowercase()

    override suspend fun register(name: String, phone: String, email: String, password: String): Result<AuthStep> = attempt {
        val username = normalize(email)
        call(
            "SignUp",
            JSONObject()
                .put("ClientId", clientId)
                .put("Username", username)
                .put("Password", password)
                .put(
                    "UserAttributes",
                    JSONArray()
                        .put(JSONObject().put("Name", "email").put("Value", username))
                        .put(JSONObject().put("Name", "name").put("Value", name.trim()))
                        .put(JSONObject().put("Name", "phone_number").put("Value", phone))
                )
        )
        AuthStep.NeedsConfirmation(username)
    }

    override suspend fun confirm(email: String, code: String): Result<Unit> = attempt {
        call(
            "ConfirmSignUp",
            JSONObject().put("ClientId", clientId).put("Username", normalize(email)).put("ConfirmationCode", code.trim())
        )
        Unit
    }

    override suspend fun resendCode(email: String): Result<Unit> = attempt {
        call("ResendConfirmationCode", JSONObject().put("ClientId", clientId).put("Username", normalize(email)))
        Unit
    }

    override suspend fun login(email: String, password: String): Result<AuthStep> {
        val username = normalize(email)
        return try {
            val response = call(
                "InitiateAuth",
                JSONObject()
                    .put("AuthFlow", "USER_PASSWORD_AUTH")
                    .put("ClientId", clientId)
                    .put(
                        "AuthParameters",
                        JSONObject().put("USERNAME", username).put("PASSWORD", password)
                    )
            )
            val result = response.optJSONObject("AuthenticationResult")
                ?: return Result.failure(IllegalStateException("Unsupported sign-in step. Please contact support."))
            Result.success(AuthStep.SignedIn(storeTokens(result)))
        } catch (e: CancellationException) {
            throw e
        } catch (e: CognitoException) {
            if (e.type == "UserNotConfirmedException") {
                resendCode(username) // best effort: a fresh code is on its way
                Result.success(AuthStep.NeedsConfirmation(username))
            } else {
                Result.failure(e)
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun accessToken(): String? = lock.withLock {
        val token = cachedIdToken ?: return null
        if (System.currentTimeMillis() < expiresAtMs - 60_000) return token
        val refresh = refreshToken ?: return null
        try {
            val response = call(
                "InitiateAuth",
                JSONObject()
                    .put("AuthFlow", "REFRESH_TOKEN_AUTH")
                    .put("ClientId", clientId)
                    .put("AuthParameters", JSONObject().put("REFRESH_TOKEN", refresh))
            )
            storeTokens(response.getJSONObject("AuthenticationResult"))
            cachedIdToken
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            clearTokens()
            null
        }
    }

    override suspend fun logout() {
        val token = refreshToken
        clearTokens()
        if (token != null) {
            // Best effort: invalidate the refresh token server-side too.
            attempt { call("RevokeToken", JSONObject().put("ClientId", clientId).put("Token", token)) }
        }
    }

    private fun clearTokens() {
        cachedIdToken = null
        refreshToken = null
        expiresAtMs = 0L
    }

    private fun storeTokens(auth: JSONObject): User {
        val id = auth.getString("IdToken")
        cachedIdToken = id
        auth.optString("RefreshToken").takeIf { it.isNotBlank() }?.let { refreshToken = it }
        expiresAtMs = System.currentTimeMillis() + auth.optLong("ExpiresIn", 3600L) * 1000
        return userFromIdToken(id)
    }

    private fun userFromIdToken(token: String): User {
        val payload = token.split('.')[1]
        val json = JSONObject(String(Base64.decode(payload, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP), Charsets.UTF_8))
        val email = json.optString("email")
        return User(
            id = json.getString("sub"),
            name = json.optString("name").ifBlank { email },
            email = email
        )
    }
}
