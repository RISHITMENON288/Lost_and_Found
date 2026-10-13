package com.example.lostandfound.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.example.lostandfound.data.Item
import com.example.lostandfound.data.User
import com.example.lostandfound.ui.components.EmptyState
import com.example.lostandfound.ui.components.ItemCard

@Composable
fun ProfileScreen(
    user: User,
    allItems: List<Item>,
    onOpen: (String) -> Unit,
    onSignOut: () -> Unit
) {
    val mine = remember(allItems, user.id) {
        allItems.filter { it.reporterId == user.id }.sortedByDescending { it.createdAt }
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(14.dp),
                modifier = Modifier.fillMaxWidth()
            ) {
                Surface(
                    shape = CircleShape,
                    color = MaterialTheme.colorScheme.primaryContainer,
                    contentColor = MaterialTheme.colorScheme.onPrimaryContainer,
                    modifier = Modifier.size(56.dp)
                ) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
                        Text(
                            user.name.take(1).uppercase(),
                            style = MaterialTheme.typography.titleLarge
                        )
                    }
                }
                Column {
                    Text(user.name, style = MaterialTheme.typography.titleLarge)
                    Text(
                        user.email,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }
        item { Text("My reports", style = MaterialTheme.typography.titleMedium) }
        if (mine.isEmpty()) {
            item {
                EmptyState(
                    emoji = "🗂️",
                    title = "No reports yet",
                    body = "Items you report as lost or found will show up here, including their status."
                )
            }
        } else {
            items(mine, key = { it.id }) { item ->
                ItemCard(item = item, onClick = { onOpen(item.id) })
            }
        }
        item {
            OutlinedButton(onClick = onSignOut, modifier = Modifier.fillMaxWidth()) { Text("Sign out") }
        }
    }
}
