package com.example.lostandfound.ui.screens

import android.content.ActivityNotFoundException
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.example.lostandfound.data.CampusLocations
import com.example.lostandfound.data.Category
import com.example.lostandfound.data.ItemType
import com.example.lostandfound.data.NewItem
import com.example.lostandfound.data.WhenOption
import com.example.lostandfound.ui.components.ItemImage
import com.example.lostandfound.util.Images
import com.example.lostandfound.util.Validators

@Composable
fun ReportScreen(
    initialType: ItemType,
    busy: Boolean,
    onBack: () -> Unit,
    onSubmit: (NewItem) -> Unit
) {
    var type by rememberSaveable { mutableStateOf(initialType) }
    var title by rememberSaveable { mutableStateOf("") }
    var category by rememberSaveable { mutableStateOf<Category?>(null) }
    var description by rememberSaveable { mutableStateOf("") }
    var location by rememberSaveable { mutableStateOf<String?>(null) }
    var whenOption by rememberSaveable { mutableStateOf(WhenOption.EARLIER_TODAY) }
    var imageUri by rememberSaveable { mutableStateOf<String?>(null) }

    var pendingCameraUri by rememberSaveable { mutableStateOf<String?>(null) }
    var photoMessage by rememberSaveable { mutableStateOf<String?>(null) }
    val context = LocalContext.current

    val picker = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri: Uri? ->
        if (uri != null) {
            imageUri = uri.toString()
            photoMessage = null
        }
    }
    // The system camera app takes the picture, so this app needs no camera permission.
    val camera = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { saved: Boolean ->
        val taken = pendingCameraUri
        if (saved && taken != null) {
            imageUri = taken
            photoMessage = null
        }
        pendingCameraUri = null
    }

    val isLost = type == ItemType.LOST
    val canSubmit = Validators.isValidTitle(title) && category != null && location != null && !busy

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = onBack) { Text("← Back") }
        }
        Text(
            if (isLost) "Report a lost item" else "Report a found item",
            style = MaterialTheme.typography.headlineSmall
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(selected = isLost, onClick = { type = ItemType.LOST }, label = { Text("I lost it") })
            FilterChip(selected = !isLost, onClick = { type = ItemType.FOUND }, label = { Text("I found it") })
        }

        // Photo
        SectionLabel("Photo (optional)")
        Surface(
            shape = RoundedCornerShape(16.dp),
            color = MaterialTheme.colorScheme.surfaceVariant,
            border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
            modifier = Modifier
                .fillMaxWidth()
                .height(170.dp)
                .clip(RoundedCornerShape(16.dp))
        ) {
            Box(contentAlignment = Alignment.Center) {
                if (imageUri != null) {
                    ItemImage(
                        imageUri = imageUri,
                        category = category ?: Category.BAG,
                        modifier = Modifier.fillMaxSize()
                    )
                } else {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text("📷", style = MaterialTheme.typography.headlineMedium)
                        Text("No photo yet", style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            OutlinedButton(
                onClick = {
                    try {
                        val target = Images.newCameraUri(context)
                        pendingCameraUri = target.toString()
                        camera.launch(target)
                    } catch (e: ActivityNotFoundException) {
                        pendingCameraUri = null
                        photoMessage = "No camera app found on this device. Choose a photo instead."
                    }
                },
                modifier = Modifier.weight(1f)
            ) { Text("📷 Take photo") }
            OutlinedButton(
                onClick = {
                    picker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
                },
                modifier = Modifier.weight(1f)
            ) { Text("🖼 Choose photo") }
        }
        photoMessage?.let {
            Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
        }
        if (imageUri != null) {
            TextButton(onClick = { imageUri = null }) { Text("Remove photo") }
        }

        OutlinedTextField(
            value = title,
            onValueChange = { if (it.length <= Validators.MAX_TITLE) title = it },
            label = { Text("What is it? (e.g. Black laptop bag)") },
            singleLine = true,
            supportingText = { Text("${title.trim().length}/${Validators.MAX_TITLE}") },
            modifier = Modifier.fillMaxWidth()
        )

        SectionLabel("Category")
        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(Category.entries.toList()) { c ->
                FilterChip(
                    selected = category == c,
                    onClick = { category = c },
                    label = { Text("${c.emoji} ${c.label}") }
                )
            }
        }

        OutlinedTextField(
            value = description,
            onValueChange = { if (it.length <= Validators.MAX_DESCRIPTION) description = it },
            label = { Text("Description (colour, brand, marks…)") },
            minLines = 3,
            supportingText = {
                Text(
                    if (isLost) "Details help us match your item. ${description.length}/${Validators.MAX_DESCRIPTION}"
                    else "Keep one identifying detail to yourself so the real owner can prove it. ${description.length}/${Validators.MAX_DESCRIPTION}"
                )
            },
            modifier = Modifier.fillMaxWidth()
        )

        SectionLabel(if (isLost) "Where did you lose it?" else "Where did you find it?")
        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(CampusLocations.all) { place ->
                FilterChip(
                    selected = location == place,
                    onClick = { location = place },
                    label = { Text(place) }
                )
            }
        }

        SectionLabel("When?")
        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(WhenOption.entries.toList()) { option ->
                FilterChip(
                    selected = whenOption == option,
                    onClick = { whenOption = option },
                    label = { Text(option.label) }
                )
            }
        }

        Spacer(Modifier.height(4.dp))
        Button(
            onClick = {
                onSubmit(
                    NewItem(
                        type = type,
                        title = title.trim(),
                        category = category!!,
                        description = description.trim(),
                        location = location!!,
                        occurredAt = System.currentTimeMillis() - whenOption.hoursAgo * 60L * 60 * 1000,
                        imageUri = imageUri
                    )
                )
            },
            enabled = canSubmit,
            modifier = Modifier.fillMaxWidth().height(52.dp)
        ) {
            if (busy) {
                CircularProgressIndicator(
                    modifier = Modifier.size(22.dp),
                    strokeWidth = 2.dp,
                    color = MaterialTheme.colorScheme.onPrimary
                )
            } else {
                Text("Submit report")
            }
        }
        Spacer(Modifier.height(16.dp))
    }
}

@Composable
private fun SectionLabel(text: String) {
    Text(text, style = MaterialTheme.typography.titleMedium)
}
