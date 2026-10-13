package com.example.lostandfound.data

import kotlinx.coroutines.flow.StateFlow

sealed interface AuthStep {
    data class SignedIn(val user: User) : AuthStep

    /** Supabase emailed a 6-digit code that must be entered before the first sign-in. */
    data class NeedsConfirmation(val email: String) : AuthStep
}

/**
 * Boundaries to the backend. The UI only talks to these interfaces, so the in-memory demo
 * versions and the Supabase versions are interchangeable (see ServiceLocator).
 */
interface AuthRepository {
    suspend fun register(name: String, phone: String, email: String, password: String): Result<AuthStep>
    suspend fun confirm(email: String, code: String): Result<Unit>
    suspend fun resendCode(email: String): Result<Unit>
    suspend fun login(email: String, password: String): Result<AuthStep>

    /** A valid access token for API calls (refreshed when needed), or null when signed out. */
    suspend fun accessToken(): String?
    suspend fun logout()
}

interface ItemRepository {
    val items: StateFlow<List<Item>>
    val matches: StateFlow<List<MatchSuggestion>>

    /** Pull the latest state from the backend (no-op for the in-memory demo). */
    suspend fun refresh()

    /** Forget everything held for the signed-in user. */
    fun clear()

    suspend fun report(user: User, draft: NewItem): Item
    suspend fun closeReport(itemId: String)
    suspend fun markReturned(itemId: String)

    /** Only the owner (the LOST reporter) confirms or rejects a suggestion. */
    suspend fun respondToMatch(matchId: String, confirm: Boolean)

    /**
     * The finder's phone number. Only the owner of the lost item gets it, and only after confirming the match;
     * the database refuses everyone else.
     */
    suspend fun contactFor(matchId: String): String
}
