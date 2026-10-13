package com.example.lostandfound.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.lostandfound.data.Item
import com.example.lostandfound.data.ItemStatus
import com.example.lostandfound.data.ItemType
import com.example.lostandfound.data.MatchState
import com.example.lostandfound.data.MatchSuggestion
import com.example.lostandfound.ui.components.ItemImage
import com.example.lostandfound.ui.components.StatusChip
import com.example.lostandfound.ui.components.TypeChip
import com.example.lostandfound.util.timeAgo

@Composable
fun DetailScreen(
    item: Item?,
    allItems: List<Item>,
    matches: List<MatchSuggestion>,
    myUserId: String,
    onBack: () -> Unit,
    onReviewMatches: () -> Unit,
    onMarkReturned: (String) -> Unit,
    onClose: (String) -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        TextButton(onClick = onBack) { Text("← Back") }

        if (item == null) {
            Text("This report is no longer available.", style = MaterialTheme.typography.bodyLarge)
            return@Column
        }

        val mine = item.reporterId == myUserId
        val involved = matches.filter { it.lostItemId == item.id || it.foundItemId == item.id }
        val pendingCount = involved.count { it.state == MatchState.PENDING }
        val confirmed = involved.firstOrNull { it.state == MatchState.CONFIRMED }
        val counterpart = confirmed?.let { m ->
            val otherId = if (m.lostItemId == item.id) m.foundItemId else m.lostItemId
            allItems.firstOrNull { it.id == otherId }
        }

        ItemImage(
            imageUri = item.imageUri,
            category = item.category,
            emojiSize = 64.sp,
            modifier = Modifier.fillMaxWidth().height(220.dp).clip(RoundedCornerShape(16.dp))
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            TypeChip(item.type)
            StatusChip(item.status)
        }
        Text(item.title, style = MaterialTheme.typography.headlineSmall)

        Surface(
            shape = RoundedCornerShape(16.dp),
            color = MaterialTheme.colorScheme.surface,
            tonalElevation = 1.dp,
            modifier = Modifier.fillMaxWidth()
        ) {
            Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                DetailRow("Category", "${item.category.emoji} ${item.category.label}")
                DetailRow(if (item.type == ItemType.LOST) "Lost at" else "Found at", item.location)
                DetailRow(if (item.type == ItemType.LOST) "Lost" else "Found", timeAgo(item.occurredAt))
                DetailRow("Reported by", if (mine) "You" else item.reporterName)
            }
        }

        if (item.description.isNotBlank()) {
            Text("Description", style = MaterialTheme.typography.titleMedium)
            Text(item.description, style = MaterialTheme.typography.bodyLarge)
        }

        if (!mine) {
            Surface(
                shape = RoundedCornerShape(16.dp),
                color = MaterialTheme.colorScheme.primaryContainer,
                contentColor = MaterialTheme.colorScheme.onPrimaryContainer
            ) {
                Text(
                    "Think this is yours? Report your lost item and we'll check for a match automatically. " +
                        "That way the owner is confirmed before any handover.",
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.padding(16.dp)
                )
            }
            return@Column
        }

        // Owner actions
        when (item.status) {
            ItemStatus.OPEN, ItemStatus.POTENTIAL_MATCH -> {
                if (pendingCount > 0) {
                    Button(onClick = onReviewMatches, modifier = Modifier.fillMaxWidth()) {
                        Text("Review $pendingCount possible match${if (pendingCount > 1) "es" else ""}")
                    }
                } else {
                    Text(
                        "No matches yet. We'll notify you as soon as something similar is reported.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                OutlinedButton(onClick = { onClose(item.id) }, modifier = Modifier.fillMaxWidth()) {
                    Text("Close this report")
                }
            }
            ItemStatus.CLAIMED -> {
                Surface(
                    shape = RoundedCornerShape(16.dp),
                    color = MaterialTheme.colorScheme.tertiaryContainer,
                    contentColor = MaterialTheme.colorScheme.onTertiaryContainer
                ) {
                    Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text("Match confirmed", style = MaterialTheme.typography.titleMedium)
                        Text(
                            if (counterpart != null)
                                "Arrange the handover with ${counterpart.reporterName} at ${counterpart.location}. " +
                                    "Meet in a public campus spot."
                            else "Arrange the handover in a public campus spot.",
                            style = MaterialTheme.typography.bodyMedium
                        )
                    }
                }
                Button(onClick = { onMarkReturned(item.id) }, modifier = Modifier.fillMaxWidth()) {
                    Text("Mark as returned")
                }
            }
            ItemStatus.RETURNED -> Text("This item was returned. 🎉", style = MaterialTheme.typography.bodyLarge)
            ItemStatus.CLOSED -> Text("This report is closed.", style = MaterialTheme.typography.bodyLarge)
        }
        Spacer(Modifier.height(16.dp))
    }
}

@Composable
private fun DetailRow(label: String, value: String) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, style = MaterialTheme.typography.bodyMedium)
    }
}
