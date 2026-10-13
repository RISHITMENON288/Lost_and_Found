package com.example.lostandfound.data

enum class ItemType(val label: String) {
    LOST("Lost"),
    FOUND("Found")
}

/**
 * Report lifecycle. A report that is simply waiting (OPEN) is shown to the user as
 * "Lost" or "Found" depending on its [ItemType].
 */
enum class ItemStatus(val label: String) {
    OPEN("Open"),
    POTENTIAL_MATCH("Potential match"),
    CLAIMED("Claimed"),
    RETURNED("Returned"),
    CLOSED("Closed")
}

/** Categories mirror the labels used by the CLIP feature extractor in the ML notebook. */
enum class Category(val label: String, val emoji: String) {
    ELECTRONICS("Electronics", "🎧"),
    BAG("Bags & luggage", "🎒"),
    CLOTHING("Clothing & footwear", "🧥"),
    ACCESSORY("Accessories & jewelry", "⌚"),
    STATIONERY("Stationery & books", "📚"),
    KEYS("Keys & tools", "🔑"),
    CONTAINER("Bottles & containers", "🥤"),
    DOCUMENTS("Documents & cards", "💳"),
    SPORTS("Sports equipment", "🏏"),
    TOYS("Toys & games", "🎲")
}

object CampusLocations {
    val all = listOf(
        "Library",
        "Main Gate",
        "Academic Block",
        "Cafeteria",
        "Hostel Area",
        "Sports Ground",
        "Auditorium",
        "Parking",
        "Other"
    )
}

/** Coarse "when did this happen" choices, kept simple for the first sprint. */
enum class WhenOption(val label: String, val hoursAgo: Int) {
    JUST_NOW("Just now", 0),
    EARLIER_TODAY("Earlier today", 5),
    YESTERDAY("Yesterday", 24),
    FEW_DAYS("2–3 days ago", 60),
    LAST_WEEK("About a week ago", 168)
}

data class User(
    val id: String,
    val name: String,
    val email: String
)

data class Item(
    val id: String,
    val type: ItemType,
    val title: String,
    val category: Category,
    val description: String,
    val location: String,
    /** When the item was lost / found (epoch millis). */
    val occurredAt: Long,
    /** A local content URI (demo mode) or a short-lived signed https link to the private photo. */
    val imageUri: String?,
    val reporterId: String,
    val reporterName: String,
    val status: ItemStatus,
    val createdAt: Long
)

/** What the report form produces; the repository turns it into an [Item]. */
data class NewItem(
    val type: ItemType,
    val title: String,
    val category: Category,
    val description: String,
    val location: String,
    val occurredAt: Long,
    val imageUri: String?
)

enum class MatchState { PENDING, CONFIRMED, REJECTED }

data class MatchSuggestion(
    val id: String,
    val lostItemId: String,
    val foundItemId: String,
    /** 0..1 estimated similarity. */
    val score: Float,
    val state: MatchState
)
