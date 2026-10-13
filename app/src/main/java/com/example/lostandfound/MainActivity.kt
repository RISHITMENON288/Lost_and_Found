package com.example.lostandfound

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import com.example.lostandfound.config.BackendConfig
import com.example.lostandfound.data.ServiceLocator
import com.example.lostandfound.notify.AppForeground
import com.example.lostandfound.ui.LostAndFoundApp
import com.example.lostandfound.ui.theme.LostAndFoundTheme

class MainActivity : ComponentActivity() {
    private val notificationPermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { /* optional: no notifications if denied */ }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        ServiceLocator.init(applicationContext)
        enableEdgeToEdge()
        setContent {
            LostAndFoundTheme {
                LostAndFoundApp()
            }
        }
        if (BackendConfig.isConfigured && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    override fun onStart() {
        super.onStart()
        AppForeground.visible = true
    }

    override fun onStop() {
        AppForeground.visible = false
        super.onStop()
    }
}
