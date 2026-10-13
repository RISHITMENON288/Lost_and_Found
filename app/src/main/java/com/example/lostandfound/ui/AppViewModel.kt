package com.example.lostandfound.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.lostandfound.config.BackendConfig
import com.example.lostandfound.data.AuthStep
import com.example.lostandfound.data.ItemType
import com.example.lostandfound.data.MatchState
import com.example.lostandfound.data.NewItem
import com.example.lostandfound.data.ServiceLocator
import com.example.lostandfound.data.CognitoException
import com.example.lostandfound.data.SupabaseException
import com.example.lostandfound.data.User
import com.example.lostandfound.net.ApiException
import com.example.lostandfound.notify.Notifier
import com.example.lostandfound.util.Validators
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.io.IOException

enum class Tab(val label: String, val glyph: String) {
    HOME("Home", "🏠"),
    MATCHES("Matches", "🔔"),
    PROFILE("Profile", "👤")
}

/** A full-screen page shown on top of the tabs. */
sealed interface Overlay {
    data class Report(val type: ItemType) : Overlay
    data class Detail(val itemId: String) : Overlay
}

data class UiState(
    val user: User? = null,
    val tab: Tab = Tab.HOME,
    val overlay: Overlay? = null,
    val busy: Boolean = false,
    val authError: String? = null,
    /** Set while the user must type the emailed verification code. */
    val confirmEmail: String? = null
)

class AppViewModel : ViewModel() {
    private val auth = ServiceLocator.auth
    private val repo = ServiceLocator.items

    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state.asStateFlow()

    val items = repo.items
    val matches = repo.matches

    /** Finder phone numbers the owner has asked to see, by match id. Memory only; cleared on sign-out. */
    private val _contacts = MutableStateFlow<Map<String, String>>(emptyMap())
    val contacts: StateFlow<Map<String, String>> = _contacts.asStateFlow()

    private val _messages = MutableSharedFlow<String>(extraBufferCapacity = 8)
    val messages: SharedFlow<String> = _messages.asSharedFlow()

    private var pendingPassword: String? = null // kept only in memory, only until verification finishes
    private var pollJob: Job? = null
    private val seenMatchIds = mutableSetOf<String>()

    // ---------------------------------------------------------------- auth

    fun signIn(email: String, password: String) {
        val error = when {
            !Validators.isValidEmail(email) -> "Enter a valid email address."
            !Validators.isValidPassword(password) -> "Password must be at least ${Validators.MIN_PASSWORD} characters."
            else -> null
        }
        if (error != null) return setAuthError(error)
        authenticate(password) { auth.login(email, password) }
    }

    fun signUp(name: String, phone: String, email: String, password: String) {
        val cleanPhone = Validators.normalizePhone(phone)
        val error = when {
            !Validators.isValidName(name) -> "Enter your name (2–50 characters)."
            cleanPhone == null -> "Enter a 10-digit mobile number, or include the country code (like +44…)."
            !Validators.isValidEmail(email) -> "Enter a valid email address."
            !Validators.isValidPassword(password) -> "Password must be at least ${Validators.MIN_PASSWORD} characters."
            else -> null
        }
        if (error != null || cleanPhone == null) return setAuthError(error ?: "Enter a valid mobile number.")
        authenticate(password) { auth.register(name, cleanPhone, email, password) }
    }

    /** User already has a code (e.g. signed up earlier) and wants to verify without signing up again. */
    fun startConfirm(email: String) {
        if (!Validators.isValidEmail(email)) return setAuthError("Enter your email address first.")
        _state.update { it.copy(confirmEmail = email.trim().lowercase(), authError = null) }
    }

    fun cancelConfirm() {
        pendingPassword = null
        _state.update { it.copy(confirmEmail = null, authError = null) }
    }

    fun confirm(code: String) {
        val email = _state.value.confirmEmail ?: return
        if (!Regex("\\d{6}").matches(code.trim())) return setAuthError("Enter the 6-digit code from your email.")
        viewModelScope.launch {
            _state.update { it.copy(busy = true, authError = null) }
            val confirmed = auth.confirm(email, code)
            if (confirmed.isFailure) {
                return@launch failAuth(confirmed.exceptionOrNull())
            }
            val password = pendingPassword
            if (password == null) {
                _state.update { it.copy(busy = false, confirmEmail = null) }
                _messages.tryEmit("Email verified. You can sign in now.")
            } else {
                handleAuthResult(auth.login(email, password))
            }
        }
    }

    fun resendCode() {
        val email = _state.value.confirmEmail ?: return
        viewModelScope.launch {
            auth.resendCode(email).fold(
                onSuccess = { _messages.tryEmit("We sent a new code to $email.") },
                onFailure = { setAuthError(describe(it)) }
            )
        }
    }

    private fun authenticate(password: String, call: suspend () -> Result<AuthStep>) {
        viewModelScope.launch {
            _state.update { it.copy(busy = true, authError = null) }
            pendingPassword = password
            handleAuthResult(call())
        }
    }

    private fun handleAuthResult(result: Result<AuthStep>) {
        result.fold(
            onSuccess = { step ->
                when (step) {
                    is AuthStep.SignedIn -> {
                        pendingPassword = null
                        seenMatchIds.clear()
                        _state.update {
                            it.copy(user = step.user, busy = false, tab = Tab.HOME, overlay = null, confirmEmail = null, authError = null)
                        }
                        startPolling()
                    }
                    is AuthStep.NeedsConfirmation ->
                        _state.update { it.copy(busy = false, confirmEmail = step.email, authError = null) }
                }
            },
            onFailure = { failAuth(it) }
        )
    }

    private fun failAuth(error: Throwable?) {
        pendingPassword = null
        _state.update { it.copy(busy = false, authError = describe(error)) }
    }

    private fun setAuthError(message: String) = _state.update { it.copy(authError = message) }

    fun clearAuthError() = _state.update { it.copy(authError = null) }

    fun signOut() {
        pollJob?.cancel()
        pendingPassword = null
        seenMatchIds.clear()
        repo.clear()
        _contacts.value = emptyMap()
        _state.value = UiState()
        viewModelScope.launch { auth.logout() }
    }

    private fun expireSession() {
        pollJob?.cancel()
        repo.clear()
        _contacts.value = emptyMap()
        _state.value = UiState(authError = "Your session expired. Please sign in again.")
    }

    // ---------------------------------------------------------------- navigation

    fun selectTab(tab: Tab) {
        _state.update { it.copy(tab = tab, overlay = null) }
        refreshNow()
    }

    fun openReport(type: ItemType) = _state.update { it.copy(overlay = Overlay.Report(type)) }

    fun openDetail(itemId: String) = _state.update { it.copy(overlay = Overlay.Detail(itemId)) }

    fun back() {
        _state.update {
            when {
                it.overlay != null -> it.copy(overlay = null)
                it.tab != Tab.HOME -> it.copy(tab = Tab.HOME)
                else -> it
            }
        }
    }

    // ---------------------------------------------------------------- reports and matches

    fun submitReport(draft: NewItem) {
        val user = _state.value.user ?: return
        launchSafely(onFinally = { _state.update { it.copy(busy = false) } }) {
            _state.update { it.copy(busy = true) }
            val item = repo.report(user, draft)
            val found = repo.matches.value.count {
                it.state == MatchState.PENDING && (it.lostItemId == item.id || it.foundItemId == item.id)
            }
            _state.update { it.copy(overlay = null, tab = Tab.HOME) }
            _messages.tryEmit(
                if (found > 0) "Report submitted. We found $found possible match${if (found > 1) "es" else ""} — check the Matches tab."
                else "Report submitted. We'll notify you if something matches."
            )
        }
    }

    fun respondToMatch(matchId: String, confirm: Boolean) {
        launchSafely {
            repo.respondToMatch(matchId, confirm)
            _messages.tryEmit(
                if (confirm) "Match confirmed. Tap “Show phone number” on the match to contact the finder."
                else "Suggestion dismissed."
            )
        }
    }

    fun showContact(matchId: String) {
        if (_contacts.value.containsKey(matchId)) return
        launchSafely {
            val number = repo.contactFor(matchId)
            _contacts.update { it + (matchId to number) }
        }
    }

    fun markReturned(itemId: String) {
        launchSafely {
            repo.markReturned(itemId)
            _messages.tryEmit("Marked as returned. Glad it found its way home!")
        }
    }

    fun closeReport(itemId: String) {
        launchSafely {
            repo.closeReport(itemId)
            _state.update { it.copy(overlay = null) }
            _messages.tryEmit("Report closed.")
        }
    }

    fun refreshNow() {
        if (!BackendConfig.isConfigured || _state.value.user == null) return
        launchSafely(quiet = true) { repo.refresh() }
    }

    // ---------------------------------------------------------------- polling and notifications

    /** Matching runs on the server after a report is saved, so we poll for new suggestions while signed in. */
    private fun startPolling() {
        pollJob?.cancel()
        if (!BackendConfig.isConfigured) return
        pollJob = viewModelScope.launch {
            var firstPass = true
            while (true) {
                try {
                    repo.refresh()
                    announceNewMatches(announce = !firstPass)
                    firstPass = false
                } catch (e: CancellationException) {
                    throw e
                } catch (e: ApiException) {
                    if (e.code == 401) {
                        expireSession()
                        return@launch
                    }
                } catch (_: Exception) {
                    // offline or a temporary server problem: try again on the next tick
                }
                delay(POLL_INTERVAL_MS)
            }
        }
    }

    /**
     * Raises an in-app message AND a system notification (banner) for each new event, once per event.
     * The first pass after sign-in only records what already exists, so old events never pop up.
     */
    private fun announceNewMatches(announce: Boolean) {
        val me = _state.value.user ?: return
        val allItems = repo.items.value
        val mine = allItems.filter { it.reporterId == me.id }.map { it.id }.toSet()

        fun notify(key: String, title: String, text: String) {
            if (!seenMatchIds.add(key) || !announce) return
            _messages.tryEmit(title)
            Notifier.show(ServiceLocator.context, key.hashCode(), title, text)
        }

        repo.matches.value.forEach { match ->
            val iAmOwner = match.lostItemId in mine
            val iAmFinder = match.foundItemId in mine
            when {
                match.state == MatchState.PENDING && iAmOwner -> notify(
                    match.id,
                    "Possible match for your lost item",
                    "“${allItems.firstOrNull { it.id == match.lostItemId }?.title ?: "Your item"}” may have been found. Open the app to review."
                )
                match.state == MatchState.PENDING && iAmFinder -> notify(
                    match.id,
                    "Someone may own the item you found",
                    "The owner will be asked to confirm. We'll tell you when they do."
                )
                match.state == MatchState.CONFIRMED && iAmFinder && !iAmOwner -> notify(
                    "confirmed:${match.id}",
                    "Your found item was claimed",
                    "The owner confirmed it is theirs and will contact you. Keep it safe until then."
                )
            }
        }
    }

    // ---------------------------------------------------------------- helpers

    private fun launchSafely(quiet: Boolean = false, onFinally: () -> Unit = {}, block: suspend () -> Unit) {
        viewModelScope.launch {
            try {
                block()
            } catch (e: CancellationException) {
                throw e
            } catch (e: ApiException) {
                if (e.code == 401) expireSession() else if (!quiet) _messages.tryEmit(e.message ?: "Request failed.")
            } catch (e: IOException) {
                if (!quiet) _messages.tryEmit(NO_CONNECTION)
            } catch (e: Exception) {
                if (!quiet) _messages.tryEmit("Something went wrong. Please try again.")
            } finally {
                onFinally()
            }
        }
    }

    private fun describe(error: Throwable?): String = when (error) {
        is SupabaseException -> error.message ?: "Something went wrong."
        is CognitoException -> error.message ?: "Something went wrong."
        is IOException -> NO_CONNECTION
        else -> "Something went wrong. Please try again."
    }

    private companion object {
        const val POLL_INTERVAL_MS = 30_000L
        const val NO_CONNECTION = "No connection. Check your internet and try again."
    }
}
