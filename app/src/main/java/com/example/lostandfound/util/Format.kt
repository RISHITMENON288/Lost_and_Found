package com.example.lostandfound.util

fun timeAgo(timestamp: Long, now: Long = System.currentTimeMillis()): String {
    val diff = (now - timestamp).coerceAtLeast(0)
    val minutes = diff / 60_000
    val hours = minutes / 60
    val days = hours / 24
    return when {
        minutes < 1 -> "just now"
        minutes < 60 -> "${minutes}m ago"
        hours < 24 -> "${hours}h ago"
        days < 7 -> "${days}d ago"
        else -> "${days / 7}w ago"
    }
}

/** Input validation shared by the UI and (later) mirrored in the backend. */
object Validators {
    private val EMAIL = Regex("^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$")

    const val MIN_PASSWORD = 8
    const val MAX_TITLE = 60
    const val MAX_DESCRIPTION = 300

    fun isValidEmail(email: String) = EMAIL.matches(email.trim())
    fun isValidPassword(password: String) = password.length >= MIN_PASSWORD
    fun isValidName(name: String) = name.trim().length in 2..50

    private val INDIA_MOBILE = Regex("^[6-9][0-9]{9}$")
    private val INTERNATIONAL = Regex("^\\+[0-9]{10,15}$")

    /**
     * Cleans a typed phone number into "+<country code><number>", or returns null if it is not plausible.
     * A plain 10-digit Indian mobile number gets +91; anything else must already start with "+".
     */
    fun normalizePhone(raw: String): String? {
        val cleaned = raw.trim().replace(Regex("[ ()\\-]"), "")
        return when {
            INDIA_MOBILE.matches(cleaned) -> "+91$cleaned"
            INTERNATIONAL.matches(cleaned) -> cleaned
            else -> null
        }
    }

    fun isValidTitle(title: String) = title.trim().length in 3..MAX_TITLE
}
