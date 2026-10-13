package com.example.lostandfound.ui.components

import android.content.Context
import android.graphics.Bitmap
import android.net.Uri
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.lostandfound.data.Category
import com.example.lostandfound.data.Item
import com.example.lostandfound.data.ItemStatus
import com.example.lostandfound.data.ItemType
import com.example.lostandfound.net.Http
import com.example.lostandfound.util.ImageCache
import com.example.lostandfound.util.Images
import com.example.lostandfound.util.timeAgo
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** Loads a local content URI or a remote https URL (signed Supabase Storage link), with an in-memory cache. */
private suspend fun loadBitmap(context: Context, source: String): Bitmap? = try {
    if (source.startsWith("https://")) {
        val response = Http.request("GET", source)
        if (response.code == 200) withContext(Dispatchers.Default) { Images.decodeBytes(response.body, 900) } else null
    } else {
        withContext(Dispatchers.IO) { Images.decodeUpright(context, Uri.parse(source), 900) }
    }
} catch (e: CancellationException) {
    throw e
} catch (_: Exception) {
    null
}

/** Shows the item's photo, or a category emoji placeholder when there is none. */
@Composable
fun ItemImage(
    imageUri: String?,
    category: Category,
    modifier: Modifier = Modifier,
    emojiSize: TextUnit = 30.sp
) {
    val placeholderColor = MaterialTheme.colorScheme.surfaceVariant
    if (imageUri == null) {
        Box(modifier.background(placeholderColor), contentAlignment = Alignment.Center) {
            Text(category.emoji, fontSize = emojiSize)
        }
        return
    }
    val context = LocalContext.current
    // Presigned URLs change on every refresh; the part before '?' identifies the picture.
    val cacheKey = imageUri.substringBefore('?')
    val bitmap by produceState<ImageBitmap?>(null, cacheKey) {
        value = (ImageCache.get(cacheKey) ?: loadBitmap(context, imageUri)?.also { ImageCache.put(cacheKey, it) })
            ?.asImageBitmap()
    }
    val loaded = bitmap
    if (loaded != null) {
        Image(
            bitmap = loaded,
            contentDescription = null,
            modifier = modifier,
            contentScale = ContentScale.Crop
        )
    } else {
        Box(modifier.background(placeholderColor), contentAlignment = Alignment.Center) {
            Text(category.emoji, fontSize = emojiSize)
        }
    }
}

@Composable
fun Chip(text: String, container: Color, content: Color, modifier: Modifier = Modifier) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(50),
        color = container,
        contentColor = content
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelMedium,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp)
        )
    }
}

@Composable
fun TypeChip(type: ItemType) {
    val colors = MaterialTheme.colorScheme
    when (type) {
        ItemType.LOST -> Chip("Lost", colors.secondaryContainer, colors.onSecondaryContainer)
        ItemType.FOUND -> Chip("Found", colors.primaryContainer, colors.onPrimaryContainer)
    }
}

@Composable
fun StatusChip(status: ItemStatus) {
    val c = MaterialTheme.colorScheme
    when (status) {
        ItemStatus.OPEN -> Unit
        ItemStatus.POTENTIAL_MATCH -> Chip(status.label, c.tertiaryContainer, c.onTertiaryContainer)
        ItemStatus.CLAIMED -> Chip(status.label, c.tertiary, c.onTertiary)
        ItemStatus.RETURNED -> Chip(status.label, c.primary, c.onPrimary)
        ItemStatus.CLOSED -> Chip(status.label, c.surfaceVariant, c.onSurfaceVariant)
    }
}

@Composable
fun ItemCard(item: Item, onClick: () -> Unit, modifier: Modifier = Modifier) {
    Card(
        onClick = onClick,
        modifier = modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant)
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            ItemImage(
                imageUri = item.imageUri,
                category = item.category,
                modifier = Modifier.size(76.dp).clip(RoundedCornerShape(12.dp))
            )
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    TypeChip(item.type)
                    StatusChip(item.status)
                }
                Text(
                    item.title,
                    style = MaterialTheme.typography.titleMedium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Text(
                    "${item.category.label} · ${item.location}",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Text(
                    timeAgo(item.occurredAt),
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.outline
                )
            }
        }
    }
}

@Composable
fun ScreenHeader(title: String, subtitle: String? = null, modifier: Modifier = Modifier) {
    Column(modifier = modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(title, style = MaterialTheme.typography.headlineMedium)
        if (subtitle != null) {
            Text(
                subtitle,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
fun EmptyState(emoji: String, title: String, body: String, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier.fillMaxWidth().padding(vertical = 40.dp, horizontal = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Text(emoji, fontSize = 40.sp)
        Text(title, style = MaterialTheme.typography.titleMedium)
        Text(
            body,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = androidx.compose.ui.text.style.TextAlign.Center
        )
    }
}
