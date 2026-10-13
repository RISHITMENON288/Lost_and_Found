package com.example.lostandfound.data

import com.example.lostandfound.net.Http
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONObject
import java.io.IOException

class SupabaseException(val code: String, message: String) : Exception(message)

/** Maps Supabase Auth error codes to messages a student can act on. Pure, so it is unit-tested. */
object SupabaseErrors {
    fun friendly(code: String, httpStatus: Int = 0): String = when (code) {
        "invalid_credentials" -> "Incorrect email or password."
        "user_already_exists", "email_exists" -> "An account with this email already exists. Try signing in."
        "weak_password" -> "Password is too weak. Use 8+ characters with letters and numbers."
        "otp_expired", "otp_disabled" -> "That code is not correct or has expired. Request a new one."
        "email_not_confirmed" -> "Please verify your email first."
        "email_address_invalid", "email_address_not_authorized" -> "That email address is not accepted."
        "signup_disabled" -> "Sign-ups are currently disabled."
        "over_email_send_rate_limit", "over_request_rate_limit", "over_sms_send_rate_limit" ->
            "Too many attempts. Please wait a minute and try again."
        "validation_failed", "bad_json" -> "Please check the details you entered."
        else -> if (httpStatus == 429) "Too many attempts. Please wait a minute and try again."
        else "Something went wrong. Please try again."
    }
}

/**
 * Talks to Supabase Auth (GoTrue) over HTTPS: sign up, email code, password sign-in, refresh, sign out.
 * Only the public anon key is used; the password travels over TLS to Supabase and is never stored.
 * Tokens are kept in memory only, so a process restart means signing in again.
 *
 * Supabase setting "Confirm email" decides the flow:
 *   ON  -> sign-up returns no session, the user enters the 6-digit code from the email.
 *   OFF -> sign-up signs the user in immediately.
 * Both are handled here.
 */
class SupabaseAuthRepository(
    baseUrl: String,
    private val anonKey: String
) : AuthRepository {
    private val authBase = baseUrl.trimEnd('/') + "/auth/v1"

    private var currentAccessToken: String? = null
    private var refreshToken: String? = null
    private var expiresAtMs = 0L
    private val lock = Mutex()

    private suspend fun call(path: String, body: JSONObject?, bearer: String? = null): JSONObject {
        val headers = mutableMapOf(
            "apikey" to anonKey,
            "Content-Type" to "application/json",
            "Accept" to "application/json"
        )
        if (bearer != null) headers["Authorization"] = "Bearer $bearer"
        val response = Http.request(
            method = "POST",
            url = authBase + path,
            headers = headers,
            body = (body ?: JSONObject()).toString().toByteArray(Charsets.UTF_8)
        )
        if (response.code in 200..299) {
            return if (response.text.isBlank()) JSONObject() else JSONObject(response.text)
        }
        val json = try {
            JSONObject(response.text)
        } catch (_: Exception) {
            null
        }
        val code = json?.optString("error_code").orEmpty()
        throw SupabaseException(code, SupabaseErrors.friendly(code, response.code))
    }

    private inline fun <T> attempt(block: () -> T): Result<T> = try {
        Result.success(block())
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        Result.failure(e)
    }

    private fun normalize(email: String) = email.trim().lowercase()

    override suspend fun register(name: String, phone: String, email: String, password: String): Result<AuthStep> = attempt<AuthStep> {
        val username = normalize(email)
        val response = call(
            "/signup",
            JSONObject()
                .put("email", username)
                .put("password", password)
                .put("data", JSONObject().put("name", name.trim()).put("phone", phone))
        )
        if (response.has("access_token")) AuthStep.SignedIn(storeSession(response)) else AuthStep.NeedsConfirmation(username)
    }

    override suspend fun confirm(email: String, code: String): Result<Unit> = attempt {
        val session = call(
            "/verify",
            JSONObject().put("type", "signup").put("email", normalize(email)).put("token", code.trim())
        )
        // Verification also opens a session. We only needed the proof that the email is real (the app signs in
        // with the password next), so close that session again. Best effort.
        val token = session.optString("access_token")
        if (token.isNotBlank() && token != "null") {
            attempt { call("/logout?scope=local", null, bearer = token) }
        }
        Unit
    }

    override suspend fun resendCode(email: String): Result<Unit> = attempt {
        call("/resend", JSONObject().put("type", "signup").put("email", normalize(email)))
        Unit
    }

    override suspend fun login(email: String, password: String): Result<AuthStep> {
        val username = normalize(email)
        return try {
            val response = call(
                "/token?grant_type=password",
                JSONObject().put("email", username).put("password", password)
            )
            Result.success(AuthStep.SignedIn(storeSession(response)))
        } catch (e: CancellationException) {
            throw e
        } catch (e: SupabaseException) {
            if (e.code == "email_not_confirmed") {
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
        val token = currentAccessToken ?: return null
        if (System.currentTimeMillis() < expiresAtMs - 60_000) return token
        val refresh = refreshToken ?: return null
        try {
            storeSession(call("/token?grant_type=refresh_token", JSONObject().put("refresh_token", refresh)))
            currentAccessToken
        } catch (e: CancellationException) {
            throw e
        } catch (e: IOException) {
            throw e // offline: keep the session, the caller reports "no connection"
        } catch (e: Exception) {
            clearTokens() // the server refused the refresh token: the user must sign in again
            null
        }
    }

    override suspend fun logout() {
        val token = currentAccessToken
        clearTokens()
        if (token != null) {
            // Best effort: invalidate this session on the server too (scope=local keeps other devices signed in).
            attempt { call("/logout?scope=local", null, bearer = token) }
        }
    }

    private fun clearTokens() {
        currentAccessToken = null
        refreshToken = null
        expiresAtMs = 0L
    }

    private fun storeSession(session: JSONObject): User {
        currentAccessToken = session.getString("access_token")
        session.optString("refresh_token").takeIf { it.isNotBlank() && it != "null" }?.let { refreshToken = it }
        expiresAtMs = System.currentTimeMillis() + session.optLong("expires_in", 3600L) * 1000

        val user = session.getJSONObject("user")
        val email = user.optString("email")
        val metadata = user.optJSONObject("user_metadata")
        val name = metadata?.optString("name").orEmpty().ifBlank { email.substringBefore('@') }
        return User(id = user.getString("id"), name = name, email = email)
    }
}
