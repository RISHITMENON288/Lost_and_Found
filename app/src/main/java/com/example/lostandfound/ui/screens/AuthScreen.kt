package com.example.lostandfound.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.example.lostandfound.ui.theme.LostAndFoundTheme
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.sp
import android.content.res.Configuration
import com.example.lostandfound.ui.theme.LostAndFoundTheme


@Composable
fun AuthScreen(
    busy: Boolean,
    error: String?,
    confirmEmail: String?,
    demoMode: Boolean,
    onSignIn: (email: String, password: String) -> Unit,
    onSignUp: (name: String, phone: String, email: String, password: String) -> Unit,
    onStartConfirm: (email: String) -> Unit,
    onConfirm: (code: String) -> Unit,
    onResend: () -> Unit,
    onCancelConfirm: () -> Unit,
    onDismissError: () -> Unit
) {
    if (confirmEmail != null) {
        ConfirmCodeContent(confirmEmail, busy, error, onConfirm, onResend, onCancelConfirm, onDismissError)
        return
    }

    var registering by rememberSaveable { mutableStateOf(false) }
    var name by rememberSaveable { mutableStateOf("") }
    var phone by rememberSaveable { mutableStateOf("") }
    var email by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp, vertical = 32.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Spacer(Modifier.height(24.dp))
        Text("🔎", fontSize = 48.sp)
        Text("Campus Lost & Found", style = MaterialTheme.typography.headlineMedium)
        Text(
            if (registering) "Create an account to report and recover items."
            else "Sign in to report or recover lost items.",
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Spacer(Modifier.height(8.dp))

        if (registering) {
            OutlinedTextField(
                value = name,
                onValueChange = { if (it.length <= 50) { name = it; onDismissError() } },
                label = { Text("Full name") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth()
            )
        }
        if (registering) {
            OutlinedTextField(
                value = phone,
                onValueChange = { if (it.length <= 16) { phone = it; onDismissError() } },
                label = { Text("Mobile number") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone),
                supportingText = {
                    Text("Shown only to the owner of an item you found, after they confirm it is theirs.")
                },
                modifier = Modifier.fillMaxWidth()
            )
        }
        OutlinedTextField(
            value = email,
            onValueChange = { if (it.length <= 100) { email = it; onDismissError() } },
            label = { Text("Email") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
            modifier = Modifier.fillMaxWidth()
        )
        OutlinedTextField(
            value = password,
            onValueChange = { if (it.length <= 64) { password = it; onDismissError() } },
            label = { Text("Password") },
            singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
            modifier = Modifier.fillMaxWidth()
        )

        if (error != null) {
            Text(error, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium)
        }

        Button(
            onClick = {
                if (registering) onSignUp(name, phone, email, password) else onSignIn(email, password)
            },
            enabled = !busy,
            modifier = Modifier.fillMaxWidth().height(52.dp)
        ) {
            if (busy) {
                CircularProgressIndicator(
                    modifier = Modifier.size(22.dp),
                    strokeWidth = 2.dp,
                    color = MaterialTheme.colorScheme.onPrimary
                )
            } else {
                Text(if (registering) "Create account" else "Sign in")
            }
        }

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                if (registering) "Already have an account?" else "New here?",
                style = MaterialTheme.typography.bodyMedium
            )
            TextButton(onClick = { registering = !registering; onDismissError() }) {
                Text(if (registering) "Sign in" else "Create account")
            }
        }

        if (!registering && !demoMode) {
            TextButton(onClick = { onStartConfirm(email) }, modifier = Modifier.fillMaxWidth()) {
                Text("I have a verification code")
            }
        }

        if (demoMode) {
            Text(
                "Demo mode: sign-in is simulated on this device. Fill in BackendConfig to use the real backend.",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.outline,
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth()
            )
        }
    }
}

@Composable
private fun ConfirmCodeContent(
    email: String,
    busy: Boolean,
    error: String?,
    onConfirm: (String) -> Unit,
    onResend: () -> Unit,
    onCancel: () -> Unit,
    onDismissError: () -> Unit
) {
    var code by rememberSaveable { mutableStateOf("") }
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp, vertical = 32.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Spacer(Modifier.height(24.dp))
        Text("📬", fontSize = 48.sp)
        Text("Check your email", style = MaterialTheme.typography.headlineMedium)
        Text(
            "We sent a 6-digit code to $email. Enter it below to verify your account.",
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        OutlinedTextField(
            value = code,
            onValueChange = { if (it.length <= 6 && it.all(Char::isDigit)) { code = it; onDismissError() } },
            label = { Text("Verification code") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
            modifier = Modifier.fillMaxWidth()
        )
        if (error != null) {
            Text(error, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium)
        }
        Button(
            onClick = { onConfirm(code) },
            enabled = !busy && code.length == 6,
            modifier = Modifier.fillMaxWidth().height(52.dp)
        ) {
            if (busy) {
                CircularProgressIndicator(
                    modifier = Modifier.size(22.dp),
                    strokeWidth = 2.dp,
                    color = MaterialTheme.colorScheme.onPrimary
                )
            } else {
                Text("Verify")
            }
        }
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            TextButton(onClick = onResend, enabled = !busy) { Text("Resend code") }
            TextButton(onClick = onCancel) { Text("Back") }
        }
    }
}


@Preview(name = "Light Mode", showBackground = true)
@Preview(name = "Dark Mode", showBackground = true, uiMode = android.content.res.Configuration.UI_MODE_NIGHT_YES)
@Composable
fun ConfirmCodePreview() {
    LostAndFoundTheme {
        ConfirmCodeContent(
            email = "rishit.menon2024@vitstudent.ac.in",
            busy = false,
            error = null,
            onConfirm = {},
            onResend = {},
            onCancel = {},
            onDismissError = {}
        )
    }
}