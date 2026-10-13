package com.example.lostandfound.data

import android.content.Context
import android.net.Uri
import com.example.lostandfound.net.ApiException
import com.example.lostandfound.net.SupabaseClient
import com.example.lostandfound.util.Images
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

/**
 * Talks to Supabase. Reads are plain table queries (the database's Row Level Security decides what this
 * user may see), a new report is one INSERT, and the other actions are database functions that check
 * ownership themselves. Matching runs inside the database when a report is saved.
 */
class SupabaseItemRepository(
    private val client: SupabaseClient,
    private val context: Context
) : ItemRepository {
    private val _items = MutableStateFlow<List<Item>>(emptyList())
    private val _matches = MutableStateFlow<List<MatchSuggestion>>(emptyList())

    override val items: StateFlow<List<Item>> = _items.asStateFlow()
    override val matches: StateFlow<List<MatchSuggestion>> = _matches.asStateFlow()

    private val refreshLock = Mutex()

    /** Private photos are shown through short-lived signed links; keep them until shortly before they expire. */
    private val signedUrls = HashMap<String, Pair<String, Long>>()

    override suspend fun refresh() = refreshLock.withLock {
        val itemRows = client.getArray("/rest/v1/items?select=$ITEM_COLUMNS&order=created_at.desc&limit=300")
        val matchRows = client.getArray("/rest/v1/matches?select=$MATCH_COLUMNS&order=created_at.desc&limit=200")

        val paths = (0 until itemRows.length())
            .mapNotNull { itemRows.optJSONObject(it)?.takeUnless { row -> row.isNull("image_path") }?.optString("image_path") }
            .filter { it.isNotBlank() }
            .toSet()
        val urls = urlsFor(paths)

        _items.value = parseList(itemRows) { parseItem(it, urls) }
        _matches.value = parseList(matchRows, ::parseMatch)
    }

    override fun clear() {
        _items.value = emptyList()
        _matches.value = emptyList()
        signedUrls.clear()
    }

    override suspend fun report(user: User, draft: NewItem): Item {
        val imagePath = draft.imageUri?.let { uploadPhoto(user.id, Uri.parse(it)) }
        val row = JSONObject()
            .put("type", draft.type.name)
            .put("title", draft.title)
            .put("category", draft.category.name)
            .put("description", draft.description)
            .put("location", draft.location)
            .put("occurred_at", draft.occurredAt)
        if (imagePath != null) row.put("image_path", imagePath)

        val created = parseItem(client.insert("items", row), emptyMap())
        refreshQuietly() // matching already ran inside the database, so new suggestions show up now
        return created
    }

    override suspend fun closeReport(itemId: String) {
        client.rpc("close_item", JSONObject().put("p_item", itemId))
        refreshQuietly()
    }

    override suspend fun markReturned(itemId: String) {
        client.rpc("mark_returned", JSONObject().put("p_item", itemId))
        refreshQuietly()
    }

    override suspend fun respondToMatch(matchId: String, confirm: Boolean) {
        client.rpc("respond_to_match", JSONObject().put("p_match", matchId).put("p_confirm", confirm))
        refreshQuietly()
    }

    override suspend fun contactFor(matchId: String): String =
        client.rpcText("get_match_contact", JSONObject().put("p_match", matchId))
            ?: throw ApiException(404, "The finder did not add a phone number.")

    /** The action itself already succeeded; a failed refresh must not make it look failed. */
    private suspend fun refreshQuietly() {
        try {
            refresh()
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
        }
    }

    /** Re-encode as a small JPEG (drops EXIF/GPS), then store it in the user's own folder of the private bucket. */
    private suspend fun uploadPhoto(userId: String, uri: Uri): String {
        val jpeg = withContext(Dispatchers.Default) { Images.toUploadJpeg(context, uri) }
        val path = "$userId/${UUID.randomUUID()}.jpg"
        client.uploadJpeg(path, jpeg)
        return path
    }

    private suspend fun urlsFor(paths: Set<String>): Map<String, String> {
        val now = System.currentTimeMillis()
        val missing = paths.filter { (signedUrls[it]?.second ?: 0L) < now + REFRESH_MARGIN_MS }
        for (chunk in missing.chunked(100)) {
            try {
                val fresh = client.signedPhotoUrls(chunk, VALID_FOR_SECONDS)
                fresh.forEach { (path, url) -> signedUrls[path] = url to now + VALID_FOR_SECONDS * 1000L }
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                // photos are optional: show the reports without them rather than failing the whole refresh
            }
        }
        return paths.mapNotNull { path -> signedUrls[path]?.let { path to it.first } }.toMap()
    }

    private fun <T : Any> parseList(array: JSONArray, parse: (JSONObject) -> T): List<T> =
        (0 until array.length()).mapNotNull { index ->
            try {
                parse(array.getJSONObject(index))
            } catch (_: Exception) {
                null // skip an entry from a newer/older backend instead of crashing the whole list
            }
        }

    private fun parseItem(o: JSONObject, urls: Map<String, String>): Item {
        val path = if (o.isNull("image_path")) null else o.getString("image_path")
        return Item(
            id = o.getString("id"),
            type = ItemType.valueOf(o.getString("type")),
            title = o.getString("title"),
            category = Category.valueOf(o.getString("category")),
            description = if (o.isNull("description")) "" else o.getString("description"),
            location = o.getString("location"),
            occurredAt = o.getLong("occurred_at"),
            imageUri = path?.let { urls[it] },
            reporterId = o.getString("reporter_id"),
            reporterName = o.getString("reporter_name"),
            status = ItemStatus.valueOf(o.getString("status")),
            createdAt = o.getLong("created_at")
        )
    }

    private fun parseMatch(o: JSONObject) = MatchSuggestion(
        id = o.getString("id"),
        lostItemId = o.getString("lost_item_id"),
        foundItemId = o.getString("found_item_id"),
        score = o.getDouble("score").toFloat(),
        state = MatchState.valueOf(o.getString("state"))
    )

    private companion object {
        const val ITEM_COLUMNS =
            "id,type,title,category,description,location,occurred_at,image_path,reporter_id,reporter_name,status,created_at"
        const val MATCH_COLUMNS = "id,lost_item_id,found_item_id,score,state"
        const val VALID_FOR_SECONDS = 3600
        const val REFRESH_MARGIN_MS = 10 * 60 * 1000L
    }
}
