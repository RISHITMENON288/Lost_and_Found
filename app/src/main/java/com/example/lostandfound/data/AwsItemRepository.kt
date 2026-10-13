package com.example.lostandfound.data

import android.content.Context
import android.net.Uri
import com.example.lostandfound.net.ApiClient
import com.example.lostandfound.net.ApiException
import com.example.lostandfound.net.Http
import com.example.lostandfound.util.Images
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.util.UUID

/** Talks to the AWS backend (API Gateway + Lambda). Matching runs server-side after a report is saved. */
class AwsItemRepository(
    private val api: ApiClient,
    private val context: Context
) : ItemRepository {
    private val _items = MutableStateFlow<List<Item>>(emptyList())
    private val _matches = MutableStateFlow<List<MatchSuggestion>>(emptyList())

    override val items: StateFlow<List<Item>> = _items.asStateFlow()
    override val matches: StateFlow<List<MatchSuggestion>> = _matches.asStateFlow()

    override suspend fun refresh() {
        val itemsJson = api.get("/items").getJSONArray("items")
        val matchesJson = api.get("/matches").getJSONArray("matches")
        _items.value = parseList(itemsJson, ::parseItem)
        _matches.value = parseList(matchesJson, ::parseMatch)
    }

    override fun clear() {
        _items.value = emptyList()
        _matches.value = emptyList()
    }

    override suspend fun report(user: User, draft: NewItem): Item {
        val imageKey = draft.imageUri?.let { uploadPhoto(Uri.parse(it)) }
        val body = JSONObject()
            .put("type", draft.type.name)
            .put("title", draft.title)
            .put("category", draft.category.name)
            .put("description", draft.description)
            .put("location", draft.location)
            .put("occurredAt", draft.occurredAt)
        if (imageKey != null) body.put("imageKey", imageKey)

        val created = parseItem(api.post("/items", body))
        refreshQuietly()
        return created
    }

    override suspend fun closeReport(itemId: String) {
        api.post("/items/$itemId/close")
        refreshQuietly()
    }

    override suspend fun markReturned(itemId: String) {
        api.post("/items/$itemId/return")
        refreshQuietly()
    }

    override suspend fun respondToMatch(matchId: String, confirm: Boolean) {
        api.post("/matches/$matchId/respond", JSONObject().put("confirm", confirm))
        refreshQuietly()
    }

    override suspend fun contactFor(matchId: String): String =
        api.get("/matches/$matchId/contact").optString("phone").ifBlank {
            throw ApiException(404, "The finder did not add a phone number.")
        }

    /** The action itself already succeeded; a failed refresh must not make it look failed. */
    private suspend fun refreshQuietly() {
        try {
            refresh()
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
        }
    }

    /** 1) re-encode as small JPEG (strips EXIF/GPS)  2) get a presigned POST  3) upload straight to S3. */
    private suspend fun uploadPhoto(uri: Uri): String {
        val jpeg = withContext(Dispatchers.Default) { Images.toUploadJpeg(context, uri) }
        val presign = api.post("/uploads", JSONObject().put("contentType", "image/jpeg"))
        val fields = presign.getJSONObject("fields")

        val boundary = "----lf" + UUID.randomUUID().toString().replace("-", "")
        val out = ByteArrayOutputStream()
        fun write(text: String) = out.write(text.toByteArray(Charsets.UTF_8))
        val names = fields.keys()
        while (names.hasNext()) {
            val name = names.next()
            write("--$boundary\r\nContent-Disposition: form-data; name=\"$name\"\r\n\r\n${fields.getString(name)}\r\n")
        }
        // S3 requires the file to be the LAST part.
        write("--$boundary\r\nContent-Disposition: form-data; name=\"file\"; filename=\"photo.jpg\"\r\n")
        write("Content-Type: image/jpeg\r\n\r\n")
        out.write(jpeg)
        write("\r\n--$boundary--\r\n")

        val response = Http.request(
            method = "POST",
            url = presign.getString("url"),
            headers = mapOf("Content-Type" to "multipart/form-data; boundary=$boundary"),
            body = out.toByteArray()
        )
        if (response.code !in 200..299) throw ApiException(response.code, "Photo upload failed. Please try again.")
        return presign.getString("key")
    }

    private fun <T : Any> parseList(array: JSONArray, parse: (JSONObject) -> T): List<T> =
        (0 until array.length()).mapNotNull { index ->
            try {
                parse(array.getJSONObject(index))
            } catch (_: Exception) {
                null // skip an entry from a newer/older backend instead of crashing the whole list
            }
        }

    private fun parseItem(o: JSONObject) = Item(
        id = o.getString("id"),
        type = ItemType.valueOf(o.getString("type")),
        title = o.getString("title"),
        category = Category.valueOf(o.getString("category")),
        description = o.optString("description", ""),
        location = o.getString("location"),
        occurredAt = o.getLong("occurredAt"),
        imageUri = if (o.isNull("imageUrl")) null else o.getString("imageUrl"),
        reporterId = o.getString("reporterId"),
        reporterName = o.getString("reporterName"),
        status = ItemStatus.valueOf(o.getString("status")),
        createdAt = o.getLong("createdAt")
    )

    private fun parseMatch(o: JSONObject) = MatchSuggestion(
        id = o.getString("id"),
        lostItemId = o.getString("lostItemId"),
        foundItemId = o.getString("foundItemId"),
        score = o.getDouble("score").toFloat(),
        state = MatchState.valueOf(o.getString("state"))
    )
}
