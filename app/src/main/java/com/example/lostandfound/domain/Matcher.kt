package com.example.lostandfound.domain

import com.example.lostandfound.data.Item
import com.example.lostandfound.data.ItemType
import kotlin.math.abs
import kotlin.math.min

/**
 * Hybrid scoring used to suggest lost/found pairs.
 *
 * Hard gates (score 0 if any fails) keep false positives down:
 *  - one LOST and one FOUND report
 *  - same category
 *  - the item was not found more than a day before it was lost
 *  - at least one shared word in title/description
 *
 * Then a weighted score of category, text similarity, location and time closeness.
 * Image similarity (CLIP embedding cosine) will be added as another weighted term
 * once the backend can compute embeddings.
 */
object Matcher {
    const val MIN_SCORE = 0.60f

    private const val W_CATEGORY = 0.20f
    private const val W_TEXT = 0.45f
    private const val W_LOCATION = 0.20f
    private const val W_TIME = 0.15f

    private const val DAY_MS = 24L * 60 * 60 * 1000
    private const val MAX_GAP_DAYS = 7.0

    private val STOP_WORDS = setOf(
        "the", "and", "with", "has", "have", "was", "were", "near", "from", "for",
        "this", "that", "there", "found", "lost", "left", "some", "very", "into",
        "onto", "its", "are", "not", "but", "inside", "side"
    )

    fun tokens(text: String): Set<String> =
        text.lowercase()
            .split(Regex("[^a-z0-9]+"))
            .filter { it.length > 2 && it !in STOP_WORDS }
            .toSet()

    /** Dice coefficient over word sets: 0 = nothing shared, 1 = identical. */
    fun textSimilarity(a: Item, b: Item): Float {
        val ta = tokens("${a.title} ${a.description}")
        val tb = tokens("${b.title} ${b.description}")
        if (ta.isEmpty() || tb.isEmpty()) return 0f
        val common = ta.intersect(tb).size
        return 2f * common / (ta.size + tb.size)
    }

    fun score(lost: Item, found: Item): Float {
        if (lost.type != ItemType.LOST || found.type != ItemType.FOUND) return 0f
        if (lost.category != found.category) return 0f
        if (found.occurredAt + DAY_MS < lost.occurredAt) return 0f

        val text = textSimilarity(lost, found)
        if (text <= 0f) return 0f

        val location = if (lost.location.equals(found.location, ignoreCase = true)) 1f else 0f
        val gapDays = abs(found.occurredAt - lost.occurredAt).toDouble() / DAY_MS
        val time = (1.0 - min(gapDays / MAX_GAP_DAYS, 1.0)).toFloat()

        return W_CATEGORY + W_TEXT * text + W_LOCATION * location + W_TIME * time
    }

    fun isMatch(score: Float): Boolean = score >= MIN_SCORE
}
