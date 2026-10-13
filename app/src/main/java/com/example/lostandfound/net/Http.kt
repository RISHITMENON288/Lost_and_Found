package com.example.lostandfound.net

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL

class HttpResponse(val code: Int, val body: ByteArray) {
    val text: String get() = body.toString(Charsets.UTF_8)
}

/** Minimal HTTPS client built on the platform, so no extra dependency is needed. */
object Http {
    private const val MAX_RESPONSE_BYTES = 8 * 1024 * 1024

    suspend fun request(
        method: String,
        url: String,
        headers: Map<String, String> = emptyMap(),
        body: ByteArray? = null
    ): HttpResponse = withContext(Dispatchers.IO) {
        require(url.startsWith("https://")) { "Only HTTPS is allowed" }
        val connection = URL(url).openConnection() as HttpURLConnection
        try {
            connection.requestMethod = method
            connection.connectTimeout = 15_000
            connection.readTimeout = 30_000
            connection.instanceFollowRedirects = false
            headers.forEach { (name, value) -> connection.setRequestProperty(name, value) }
            if (body != null) {
                connection.doOutput = true
                connection.setFixedLengthStreamingMode(body.size)
                connection.outputStream.use { it.write(body) }
            }
            val code = connection.responseCode
            val stream = if (code < 400) connection.inputStream else connection.errorStream
            HttpResponse(code, stream?.use { readLimited(it) } ?: ByteArray(0))
        } finally {
            connection.disconnect()
        }
    }

    private fun readLimited(input: InputStream): ByteArray {
        val out = ByteArrayOutputStream()
        val buffer = ByteArray(8192)
        var total = 0
        while (true) {
            val read = input.read(buffer)
            if (read < 0) break
            total += read
            if (total > MAX_RESPONSE_BYTES) throw IOException("Response too large")
            out.write(buffer, 0, read)
        }
        return out.toByteArray()
    }
}

class ApiException(val code: Int, message: String) : Exception(message)

/**
 * Talks to Supabase's data APIs (PostgREST for tables and functions, Storage for photos).
 * Every call carries the public anon key plus the signed-in user's access token; what the user may
 * actually read or change is decided by the database's Row Level Security, not by this app.
 */
class SupabaseClient(
    baseUrl: String,
    private val anonKey: String,
    private val accessToken: suspend () -> String?
) {
    private val base = baseUrl.trimEnd('/')

    private suspend fun call(
        method: String,
        path: String,
        body: ByteArray? = null,
        contentType: String = "application/json",
        extraHeaders: Map<String, String> = emptyMap()
    ): HttpResponse {
        val token = accessToken() ?: throw ApiException(401, "Please sign in again.")
        val headers = mutableMapOf(
            "apikey" to anonKey,
            "Authorization" to "Bearer $token",
            "Accept" to "application/json"
        )
        if (body != null) headers["Content-Type"] = contentType
        headers.putAll(extraHeaders)

        val response = Http.request(method, base + path, headers, body)
        if (response.code in 200..299) return response
        throw toException(response)
    }

    /** Only messages that WE wrote in the database (error codes PT4xx) are shown; anything else stays generic. */
    private fun toException(response: HttpResponse): ApiException {
        val json = try {
            JSONObject(response.text)
        } catch (_: Exception) {
            null
        }
        val code = json?.optString("code").orEmpty()
        val message = json?.optString("message").orEmpty()
        val expiredToken = message.contains("jwt", ignoreCase = true) && response.code in 400..403
        return when {
            code.startsWith("PT") && message.isNotBlank() -> ApiException(response.code, message)
            response.code == 401 || expiredToken -> ApiException(401, "Please sign in again.")
            response.code == 413 -> ApiException(413, "That file is too large.")
            response.code == 429 -> ApiException(429, "Too many requests. Please wait a moment.")
            else -> ApiException(response.code, "Request failed (${response.code}).")
        }
    }

    suspend fun getArray(path: String): JSONArray = JSONArray(call("GET", path).text)

    /** Inserts one row and returns it as stored (including values the database filled in). */
    suspend fun insert(table: String, row: JSONObject): JSONObject {
        val response = call(
            "POST", "/rest/v1/$table", row.toString().toByteArray(Charsets.UTF_8),
            extraHeaders = mapOf("Prefer" to "return=representation")
        )
        return JSONArray(response.text).getJSONObject(0)
    }

    /** Calls a database function (close_item, mark_returned, respond_to_match). The response body is not needed. */
    suspend fun rpc(function: String, args: JSONObject) {
        call("POST", "/rest/v1/rpc/$function", args.toString().toByteArray(Charsets.UTF_8))
    }

    /** Calls a database function that returns one text value (PostgREST sends it as a JSON string). */
    suspend fun rpcText(function: String, args: JSONObject): String? {
        val text = call("POST", "/rest/v1/rpc/$function", args.toString().toByteArray(Charsets.UTF_8)).text.trim()
        val value = JSONTokener(text).nextValue()
        return if (value is String && value.isNotBlank()) value else null
    }

    suspend fun uploadJpeg(objectPath: String, bytes: ByteArray) {
        call(
            "POST", "/storage/v1/object/$PHOTO_BUCKET/$objectPath", bytes,
            contentType = "image/jpeg",
            extraHeaders = mapOf("x-upsert" to "false")
        )
    }

    /** One request returns time-limited links for many private photos: path -> full https URL. */
    suspend fun signedPhotoUrls(paths: List<String>, validForSeconds: Int = 3600): Map<String, String> {
        if (paths.isEmpty()) return emptyMap()
        val body = JSONObject().put("expiresIn", validForSeconds).put("paths", JSONArray(paths))
        val array = JSONArray(
            call("POST", "/storage/v1/object/sign/$PHOTO_BUCKET", body.toString().toByteArray(Charsets.UTF_8)).text
        )
        val result = HashMap<String, String>()
        for (i in 0 until array.length()) {
            val entry = array.optJSONObject(i) ?: continue
            val path = entry.optString("path")
            val signed = if (entry.isNull("signedURL")) "" else entry.optString("signedURL")
            if (path.isBlank() || signed.isBlank()) continue
            result[path] = if (signed.startsWith("http")) signed
            else if (signed.startsWith("/storage/v1")) base + signed
            else "$base/storage/v1$signed"
        }
        return result
    }

    private companion object {
        const val PHOTO_BUCKET = "item-photos"
    }
}

/** Pure helper (unit-tested): turns a failed API response into the message the user sees. */
object ApiErrors {
    fun message(status: Int, body: String): String {
        if (status == 401) return "Please sign in again."
        val fromServer = try {
            JSONObject(body).optString("error")
        } catch (_: Exception) {
            ""
        }
        return when {
            fromServer.isNotBlank() -> fromServer // our own Lambda wrote this text, it is meant for the user
            status == 429 -> "Too many requests. Please wait a moment."
            status == 413 -> "That file is too large."
            else -> "Request failed ($status)."
        }
    }
}

/**
 * Talks to the AWS API (API Gateway + Lambda). Every call carries the Cognito ID token; API Gateway checks it
 * before the Lambda runs, and the Lambda decides what this user may see or change.
 */
class ApiClient(
    private val baseUrl: String,
    private val idToken: suspend () -> String?
) {
    suspend fun get(path: String): JSONObject = call("GET", path, null)

    suspend fun post(path: String, body: JSONObject = JSONObject()): JSONObject = call("POST", path, body)

    private suspend fun call(method: String, path: String, body: JSONObject?): JSONObject {
        val token = idToken() ?: throw ApiException(401, "Please sign in again.")
        val headers = mutableMapOf("Authorization" to "Bearer $token", "Accept" to "application/json")
        if (body != null) headers["Content-Type"] = "application/json"

        val response = Http.request(
            method = method,
            url = baseUrl.trimEnd('/') + path,
            headers = headers,
            body = body?.toString()?.toByteArray(Charsets.UTF_8)
        )
        if (response.code in 200..299) return if (response.text.isBlank()) JSONObject() else JSONObject(response.text)
        throw ApiException(response.code, ApiErrors.message(response.code, response.text))
    }
}
