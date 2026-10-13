package com.example.lostandfound.data

import android.content.Context
import com.example.lostandfound.config.BackendConfig
import com.example.lostandfound.domain.Matcher
import com.example.lostandfound.net.ApiClient
import com.example.lostandfound.net.SupabaseClient
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import java.util.UUID

/**
 * DEMO ONLY. No passwords are stored or checked; any well-formed email signs in.
 * Used automatically while BackendConfig is blank.
 */
class MockAuthRepository : AuthRepository {
    private val users = mutableMapOf<String, User>()

    override suspend fun register(name: String, phone: String, email: String, password: String): Result<AuthStep> {
        delay(400)
        val key = email.trim().lowercase()
        val user = User(UUID.randomUUID().toString(), name.trim(), key)
        users[key] = user
        return Result.success(AuthStep.SignedIn(user))
    }

    override suspend fun confirm(email: String, code: String): Result<Unit> = Result.success(Unit)

    override suspend fun resendCode(email: String): Result<Unit> = Result.success(Unit)

    override suspend fun login(email: String, password: String): Result<AuthStep> {
        delay(400)
        val key = email.trim().lowercase()
        val user = users.getOrPut(key) {
            User(UUID.randomUUID().toString(), key.substringBefore('@').replaceFirstChar { it.uppercase() }, key)
        }
        return Result.success(AuthStep.SignedIn(user))
    }

    override suspend fun accessToken(): String? = null

    override suspend fun logout() = Unit
}

/** Keeps everything in memory and runs the [Matcher] on every new report. */
class InMemoryItemRepository : ItemRepository {
    private val _items = MutableStateFlow(SeedData.items())
    private val _matches = MutableStateFlow<List<MatchSuggestion>>(emptyList())

    override val items: StateFlow<List<Item>> = _items.asStateFlow()
    override val matches: StateFlow<List<MatchSuggestion>> = _matches.asStateFlow()

    override suspend fun refresh() = Unit

    override fun clear() = Unit

    override suspend fun report(user: User, draft: NewItem): Item {
        delay(500)
        val item = Item(
            id = UUID.randomUUID().toString(),
            type = draft.type,
            title = draft.title,
            category = draft.category,
            description = draft.description,
            location = draft.location,
            occurredAt = draft.occurredAt,
            imageUri = draft.imageUri,
            reporterId = user.id,
            reporterName = user.name,
            status = ItemStatus.OPEN,
            createdAt = System.currentTimeMillis()
        )
        _items.update { it + item }
        runMatching(item)
        return item
    }

    private fun runMatching(newItem: Item) {
        val open = setOf(ItemStatus.OPEN, ItemStatus.POTENTIAL_MATCH)
        val created = _items.value
            .filter { it.type != newItem.type && it.status in open && it.reporterId != newItem.reporterId }
            .mapNotNull { other ->
                val lost = if (newItem.type == ItemType.LOST) newItem else other
                val found = if (newItem.type == ItemType.FOUND) newItem else other
                val score = Matcher.score(lost, found)
                if (Matcher.isMatch(score)) {
                    MatchSuggestion(UUID.randomUUID().toString(), lost.id, found.id, score, MatchState.PENDING)
                } else null
            }
        if (created.isEmpty()) return

        _matches.update { it + created }
        val ids = created.flatMap { listOf(it.lostItemId, it.foundItemId) }.toSet()
        _items.update { list ->
            list.map { if (it.id in ids && it.status == ItemStatus.OPEN) it.copy(status = ItemStatus.POTENTIAL_MATCH) else it }
        }
    }

    override suspend fun respondToMatch(matchId: String, confirm: Boolean) {
        delay(300)
        val match = _matches.value.firstOrNull { it.id == matchId && it.state == MatchState.PENDING } ?: return
        if (confirm) {
            _matches.update { list ->
                list.map { m ->
                    when {
                        m.id == matchId -> m.copy(state = MatchState.CONFIRMED)
                        m.state == MatchState.PENDING &&
                            (m.lostItemId == match.lostItemId || m.foundItemId == match.foundItemId) ->
                            m.copy(state = MatchState.REJECTED)
                        else -> m
                    }
                }
            }
            setStatus(setOf(match.lostItemId, match.foundItemId), ItemStatus.CLAIMED)
        } else {
            _matches.update { list -> list.map { if (it.id == matchId) it.copy(state = MatchState.REJECTED) else it } }
        }
        revertStalePotentialMatches()
    }

    override suspend fun contactFor(matchId: String): String {
        delay(200)
        return "+919876543210" // demo only: a made-up number
    }

    override suspend fun markReturned(itemId: String) {
        delay(300)
        val confirmed = _matches.value.firstOrNull {
            it.state == MatchState.CONFIRMED && (it.lostItemId == itemId || it.foundItemId == itemId)
        }
        val ids = confirmed?.let { setOf(it.lostItemId, it.foundItemId) } ?: setOf(itemId)
        setStatus(ids, ItemStatus.RETURNED)
    }

    override suspend fun closeReport(itemId: String) {
        delay(300)
        _matches.update { list ->
            list.map {
                if (it.state == MatchState.PENDING && (it.lostItemId == itemId || it.foundItemId == itemId)) {
                    it.copy(state = MatchState.REJECTED)
                } else it
            }
        }
        setStatus(setOf(itemId), ItemStatus.CLOSED)
        revertStalePotentialMatches()
    }

    private fun setStatus(ids: Set<String>, status: ItemStatus) {
        _items.update { list -> list.map { if (it.id in ids) it.copy(status = status) else it } }
    }

    /** An item marked POTENTIAL_MATCH with no pending suggestion left goes back to OPEN. */
    private fun revertStalePotentialMatches() {
        val pending = _matches.value.filter { it.state == MatchState.PENDING }
        val stillMatched = pending.flatMap { listOf(it.lostItemId, it.foundItemId) }.toSet()
        _items.update { list ->
            list.map {
                if (it.status == ItemStatus.POTENTIAL_MATCH && it.id !in stillMatched) it.copy(status = ItemStatus.OPEN) else it
            }
        }
    }
}

/**
 * Chooses the backend once, from BackendConfig.BACKEND: AWS (Cognito + API Gateway + Lambda) or Supabase.
 * While the chosen backend is not filled in, the app runs fully on-device with the demo implementations.
 */
object ServiceLocator {
    private var appContext: Context? = null

    fun init(context: Context) {
        appContext = context.applicationContext
    }

    val context: Context
        get() = checkNotNull(appContext) { "ServiceLocator.init() must be called first" }

    val auth: AuthRepository by lazy {
        if (BackendConfig.useAws) {
            CognitoAuthRepository(BackendConfig.AWS_REGION, BackendConfig.COGNITO_CLIENT_ID)
        } else if (BackendConfig.isConfigured) {
            SupabaseAuthRepository(BackendConfig.SUPABASE_URL, BackendConfig.SUPABASE_ANON_KEY)
        } else {
            MockAuthRepository()
        }
    }

    val items: ItemRepository by lazy {
        if (BackendConfig.useAws) {
            AwsItemRepository(ApiClient(BackendConfig.AWS_API_URL) { auth.accessToken() }, context)
        } else if (BackendConfig.isConfigured) {
            SupabaseItemRepository(SupabaseClient(BackendConfig.SUPABASE_URL, BackendConfig.SUPABASE_ANON_KEY) { auth.accessToken() }, context)
        } else {
            InMemoryItemRepository()
        }
    }
}

private object SeedData {
    private const val HOUR = 60L * 60 * 1000

    fun items(): List<Item> {
        val now = System.currentTimeMillis()
        fun item(
            id: String, type: ItemType, title: String, category: Category, description: String,
            location: String, hoursAgo: Long, reporter: String
        ) = Item(
            id = id, type = type, title = title, category = category, description = description,
            location = location, occurredAt = now - hoursAgo * HOUR, imageUri = null,
            reporterId = "seed-$reporter", reporterName = reporter, status = ItemStatus.OPEN,
            createdAt = now - hoursAgo * HOUR
        )
        return listOf(
            item("s1", ItemType.FOUND, "Black laptop bag with charger", Category.BAG,
                "Black backpack with a Dell laptop charger inside, left on a bench.", "Library", 5, "Riya S."),
            item("s2", ItemType.FOUND, "Blue steel water bottle", Category.CONTAINER,
                "Blue steel bottle with a cat sticker on the side.", "Cafeteria", 26, "Arjun M."),
            item("s3", ItemType.FOUND, "Student ID card", Category.DOCUMENTS,
                "ID card on a green lanyard, name partly worn off.", "Academic Block", 3, "Neha K."),
            item("s4", ItemType.FOUND, "Wireless earbuds case", Category.ELECTRONICS,
                "White charging case, no earbuds inside.", "Sports Ground", 50, "Riya S."),
            item("s5", ItemType.LOST, "Casio scientific calculator", Category.STATIONERY,
                "Casio fx-991 calculator with a scratched back cover.", "Academic Block", 48, "Arjun M."),
            item("s6", ItemType.LOST, "Silver wrist watch", Category.ACCESSORY,
                "Silver analog watch with a brown leather strap.", "Auditorium", 24, "Neha K."),
            item("s7", ItemType.LOST, "Hostel room keys", Category.KEYS,
                "Three keys on a red keychain with a bottle opener.", "Hostel Area", 6, "Riya S.")
        )
    }
}
