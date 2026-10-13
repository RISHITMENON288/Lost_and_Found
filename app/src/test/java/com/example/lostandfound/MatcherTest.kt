package com.example.lostandfound

import com.example.lostandfound.data.Category
import com.example.lostandfound.data.Item
import com.example.lostandfound.data.ItemStatus
import com.example.lostandfound.data.ItemType
import com.example.lostandfound.domain.Matcher
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MatcherTest {
    private val hour = 60L * 60 * 1000
    private val now = 1_800_000_000_000L

    private fun item(
        type: ItemType,
        title: String,
        description: String = "",
        category: Category = Category.BAG,
        location: String = "Library",
        at: Long = now
    ) = Item(
        id = title + type, type = type, title = title, category = category,
        description = description, location = location, occurredAt = at, imageUri = null,
        reporterId = type.name, reporterName = type.name, status = ItemStatus.OPEN, createdAt = at
    )

    @Test
    fun strongMatchIsSuggested() {
        val lost = item(ItemType.LOST, "Black laptop bag", "Black backpack with Dell charger")
        val found = item(ItemType.FOUND, "Black laptop bag with charger", "Black backpack, Dell charger inside", at = now + 3 * hour)
        val score = Matcher.score(lost, found)
        assertTrue("score was $score", Matcher.isMatch(score))
    }

    @Test
    fun differentCategoryNeverMatches() {
        val lost = item(ItemType.LOST, "Black laptop bag")
        val found = item(ItemType.FOUND, "Black laptop bag", category = Category.ELECTRONICS)
        assertEquals(0f, Matcher.score(lost, found), 0f)
    }

    @Test
    fun noSharedWordsNeverMatches() {
        val lost = item(ItemType.LOST, "Black laptop bag")
        val found = item(ItemType.FOUND, "Umbrella", "Folding rain cover")
        assertEquals(0f, Matcher.score(lost, found), 0f)
    }

    @Test
    fun foundLongBeforeLostIsRejected() {
        val lost = item(ItemType.LOST, "Black laptop bag", at = now)
        val found = item(ItemType.FOUND, "Black laptop bag", at = now - 48 * hour)
        assertEquals(0f, Matcher.score(lost, found), 0f)
    }

    @Test
    fun wrongTypesScoreZero() {
        val a = item(ItemType.LOST, "Black laptop bag")
        val b = item(ItemType.LOST, "Black laptop bag")
        assertEquals(0f, Matcher.score(a, b), 0f)
    }

    @Test
    fun weakTextOverlapInDifferentPlaceIsNotSuggested() {
        val lost = item(ItemType.LOST, "Black bag", "Small shoulder bag", location = "Library")
        val found = item(ItemType.FOUND, "Black duffel bag", "Large gym duffel with zip pockets", location = "Parking", at = now + 120 * hour)
        assertFalse(Matcher.isMatch(Matcher.score(lost, found)))
    }
}
