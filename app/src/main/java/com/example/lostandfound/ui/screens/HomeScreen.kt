package com.example.lostandfound.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.example.lostandfound.data.Item
import com.example.lostandfound.data.ItemStatus
import com.example.lostandfound.data.ItemType
import com.example.lostandfound.ui.components.EmptyState
import com.example.lostandfound.ui.components.ItemCard
import com.example.lostandfound.ui.components.ScreenHeader

@Composable
fun HomeScreen(
    allItems: List<Item>,
    onReport: (ItemType) -> Unit,
    onOpen: (String) -> Unit
) {
    var query by rememberSaveable { mutableStateOf("") }
    var filter by rememberSaveable { mutableStateOf<ItemType?>(null) }

    val visible = remember(allItems, query, filter) {
        val shown = setOf(ItemStatus.OPEN, ItemStatus.POTENTIAL_MATCH)
        allItems
            .filter { it.status in shown }
            .filter { filter == null || it.type == filter }
            .filter { item ->
                query.isBlank() || listOf(item.title, item.description, item.location, item.category.label)
                    .any { it.contains(query.trim(), ignoreCase = true) }
            }
            .sortedByDescending { it.createdAt }
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 16.dp, vertical = 16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item {
            ScreenHeader("Campus Lost & Found", "Report something, or browse what others have posted.")
        }
        item {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Button(
                    onClick = { onReport(ItemType.LOST) },
                    modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.secondary,
                        contentColor = MaterialTheme.colorScheme.onSecondary
                    )
                ) { Text("I lost something") }
                Button(
                    onClick = { onReport(ItemType.FOUND) },
                    modifier = Modifier.weight(1f)
                ) { Text("I found something") }
            }
        }
        item {
            OutlinedTextField(
                value = query,
                onValueChange = { if (it.length <= 60) query = it },
                label = { Text("Search items, places, categories") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth()
            )
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(selected = filter == null, onClick = { filter = null }, label = { Text("All") })
                FilterChip(selected = filter == ItemType.LOST, onClick = { filter = ItemType.LOST }, label = { Text("Lost") })
                FilterChip(selected = filter == ItemType.FOUND, onClick = { filter = ItemType.FOUND }, label = { Text("Found") })
            }
        }
        if (visible.isEmpty()) {
            item {
                EmptyState(
                    emoji = "📭",
                    title = "Nothing here yet",
                    body = "No reports match your search. Try clearing the filter, or post your own report."
                )
            }
        } else {
            items(visible, key = { it.id }) { item ->
                ItemCard(item = item, onClick = { onOpen(item.id) })
            }
        }
    }
}
