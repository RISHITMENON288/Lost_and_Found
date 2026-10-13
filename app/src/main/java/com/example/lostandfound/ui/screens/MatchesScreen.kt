package com.example.lostandfound.ui.screens

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.example.lostandfound.data.Item
import com.example.lostandfound.data.ItemStatus
import com.example.lostandfound.data.MatchState
import com.example.lostandfound.data.MatchSuggestion
import com.example.lostandfound.ui.components.Chip
import com.example.lostandfound.ui.components.EmptyState
import com.example.lostandfound.ui.components.ItemImage
import com.example.lostandfound.ui.components.ScreenHeader
import com.example.lostandfound.util.timeAgo
import kotlin.math.roundToInt

private data class MatchCard(val match: MatchSuggestion, val lost: Item, val found: Item)

@Composable
fun MatchesScreen(
    allItems: List<Item>,
    matches: List<MatchSuggestion>,
    myUserId: String,
    contacts: Map<String, String>,
    onOpen: (String) -> Unit,
    onRespond: (matchId: String, confirm: Boolean) -> Unit,
    onShowContact: (matchId: String) -> Unit
) {
    val cards = remember(allItems, matches, myUserId) {
        matches.mapNotNull { m ->
            val lost = allItems.firstOrNull { it.id == m.lostItemId }
            val found = allItems.firstOrNull { it.id == m.foundItemId }
            if (lost == null || found == null) null
            else if (lost.reporterId != myUserId && found.reporterId != myUserId) null
            else MatchCard(m, lost, found)
        }.sortedWith(
            compareBy<MatchCard> { it.match.state != MatchState.PENDING }
                .thenByDescending { it.match.score }
        )
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item {
            ScreenHeader(
                "Matches",
                "Suggestions are estimates. Only confirm if the item is really yours."
            )
        }
        if (cards.isEmpty()) {
            item {
                EmptyState(
                    emoji = "🔔",
                    title = "No matches yet",
                    body = "Report a lost or found item and we'll check it against everything else on campus."
                )
            }
        } else {
            items(cards, key = { it.match.id }) { card ->
                MatchCardView(card, myUserId, contacts[card.match.id], onOpen, onRespond, onShowContact)
            }
        }
    }
}

@Composable
private fun MatchCardView(
    card: MatchCard,
    myUserId: String,
    phone: String?,
    onOpen: (String) -> Unit,
    onRespond: (String, Boolean) -> Unit,
    onShowContact: (String) -> Unit
) {
    val m = card.match
    val iAmOwner = card.lost.reporterId == myUserId
    val c = MaterialTheme.colorScheme

    Card(
        colors = CardDefaults.cardColors(containerColor = c.surface),
        border = BorderStroke(1.dp, c.outlineVariant),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween,
                modifier = Modifier.fillMaxWidth()) {
                Chip("${(m.score * 100).roundToInt()}% similar", c.tertiaryContainer, c.onTertiaryContainer)
                when (m.state) {
                    MatchState.PENDING -> Unit
                    MatchState.CONFIRMED -> Chip("Confirmed", c.primary, c.onPrimary)
                    MatchState.REJECTED -> Chip("Dismissed", c.surfaceVariant, c.onSurfaceVariant)
                }
            }
            MiniItem("Lost", card.lost, onOpen)
            MiniItem("Found", card.found, onOpen)

            when {
                m.state == MatchState.PENDING && iAmOwner -> Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Button(onClick = { onRespond(m.id, true) }, modifier = Modifier.weight(1f)) { Text("This is mine") }
                    OutlinedButton(onClick = { onRespond(m.id, false) }, modifier = Modifier.weight(1f)) { Text("Not mine") }
                }
                m.state == MatchState.PENDING ->
                    Text("Waiting for the owner to confirm.", style = MaterialTheme.typography.bodyMedium, color = c.onSurfaceVariant)
                m.state == MatchState.CONFIRMED && iAmOwner && card.lost.status == ItemStatus.CLAIMED ->
                    ContactBlock(card.found.reporterName, phone) { onShowContact(m.id) }
                m.state == MatchState.CONFIRMED && iAmOwner ->
                    Text("This item is no longer waiting for pickup.", style = MaterialTheme.typography.bodyMedium, color = c.onSurfaceVariant)
                m.state == MatchState.CONFIRMED ->
                    Text(
                        "Hand it over to ${card.lost.reporterName}. They will contact you.",
                        style = MaterialTheme.typography.bodyMedium
                    )
                else -> Unit
            }
        }
    }
}

/** The finder's number is fetched only when the owner taps, and only the owner is allowed to get it. */
@Composable
private fun ContactBlock(finderName: String, phone: String?, onShow: () -> Unit) {
    val context = LocalContext.current
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Contact $finderName to collect your item.", style = MaterialTheme.typography.bodyMedium)
        if (phone == null) {
            Button(onClick = onShow, modifier = Modifier.fillMaxWidth()) { Text("Show phone number") }
        } else {
            Text(phone, style = MaterialTheme.typography.titleMedium)
            Button(
                onClick = {
                    try {
                        context.startActivity(Intent(Intent.ACTION_DIAL, Uri.fromParts("tel", phone, null)))
                    } catch (_: ActivityNotFoundException) {
                        // no phone app: the number is still shown above
                    }
                },
                modifier = Modifier.fillMaxWidth()
            ) { Text("📞 Call $finderName") }
        }
    }
}

@Composable
private fun MiniItem(label: String, item: Item, onOpen: (String) -> Unit) {
    androidx.compose.material3.Surface(
        onClick = { onOpen(item.id) },
        shape = RoundedCornerShape(12.dp),
        color = MaterialTheme.colorScheme.background,
        modifier = Modifier.fillMaxWidth()
    ) {
        Row(
            modifier = Modifier.padding(8.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            ItemImage(
                imageUri = item.imageUri,
                category = item.category,
                modifier = Modifier.size(52.dp).clip(RoundedCornerShape(10.dp))
            )
            Column(modifier = Modifier.weight(1f)) {
                Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.outline)
                Text(item.title, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(
                    "${item.location} · ${timeAgo(item.occurredAt)}",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
        }
    }
}
