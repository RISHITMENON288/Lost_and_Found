package com.example.lostandfound.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.lostandfound.config.BackendConfig
import com.example.lostandfound.data.MatchState
import com.example.lostandfound.ui.screens.AuthScreen
import com.example.lostandfound.ui.screens.DetailScreen
import com.example.lostandfound.ui.screens.HomeScreen
import com.example.lostandfound.ui.screens.MatchesScreen
import com.example.lostandfound.ui.screens.ProfileScreen
import com.example.lostandfound.ui.screens.ReportScreen

@Composable
fun LostAndFoundApp(vm: AppViewModel = viewModel()) {
    val state by vm.state.collectAsState()
    val items by vm.items.collectAsState()
    val matches by vm.matches.collectAsState()
    val contacts by vm.contacts.collectAsState()
    val snackbar = remember { SnackbarHostState() }

    LaunchedEffect(Unit) {
        vm.messages.collect { snackbar.showSnackbar(it) }
    }

    val user = state.user
    val overlay = state.overlay

    BackHandler(enabled = user != null && (overlay != null || state.tab != Tab.HOME)) { vm.back() }

    val pendingForMe = if (user == null) 0 else {
        val mine = items.filter { it.reporterId == user.id }.map { it.id }.toSet()
        matches.count { it.state == MatchState.PENDING && (it.lostItemId in mine || it.foundItemId in mine) }
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = {
            if (user != null && overlay == null) {
                NavigationBar {
                    Tab.entries.forEach { tab ->
                        NavigationBarItem(
                            selected = state.tab == tab,
                            onClick = { vm.selectTab(tab) },
                            icon = { Text(tab.glyph) },
                            label = {
                                Text(if (tab == Tab.MATCHES && pendingForMe > 0) "Matches ($pendingForMe)" else tab.label)
                            }
                        )
                    }
                }
            }
        }
    ) { padding ->
        Box(modifier = Modifier.fillMaxSize().padding(padding)) {
            if (user == null) {
                AuthScreen(
                    busy = state.busy,
                    error = state.authError,
                    confirmEmail = state.confirmEmail,
                    demoMode = !BackendConfig.isConfigured,
                    onSignIn = vm::signIn,
                    onSignUp = vm::signUp,
                    onStartConfirm = vm::startConfirm,
                    onConfirm = vm::confirm,
                    onResend = vm::resendCode,
                    onCancelConfirm = vm::cancelConfirm,
                    onDismissError = vm::clearAuthError
                )
            } else if (overlay is Overlay.Report) {
                ReportScreen(
                    initialType = overlay.type,
                    busy = state.busy,
                    onBack = vm::back,
                    onSubmit = vm::submitReport
                )
            } else if (overlay is Overlay.Detail) {
                DetailScreen(
                    item = items.firstOrNull { it.id == overlay.itemId },
                    allItems = items,
                    matches = matches,
                    myUserId = user.id,
                    onBack = vm::back,
                    onReviewMatches = { vm.selectTab(Tab.MATCHES) },
                    onMarkReturned = vm::markReturned,
                    onClose = vm::closeReport
                )
            } else {
                when (state.tab) {
                    Tab.HOME -> HomeScreen(
                        allItems = items,
                        onReport = vm::openReport,
                        onOpen = vm::openDetail
                    )
                    Tab.MATCHES -> MatchesScreen(
                        allItems = items,
                        matches = matches,
                        myUserId = user.id,
                        contacts = contacts,
                        onOpen = vm::openDetail,
                        onRespond = vm::respondToMatch,
                        onShowContact = vm::showContact
                    )
                    Tab.PROFILE -> ProfileScreen(
                        user = user,
                        allItems = items,
                        onOpen = vm::openDetail,
                        onSignOut = vm::signOut
                    )
                }
            }
        }
    }
}
