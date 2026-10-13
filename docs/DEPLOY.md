# Setting up the backend (Supabase)

You need a free Supabase account and about 15 minutes. Nothing here needs a terminal.

> **Never put the `service_role` / "secret" key in the app, in GitHub, or in a chat.** It bypasses every security rule.
> The app only contains the project URL and the **publishable (anon) key**, which are made to be public.

## 1. Create the project
1. supabase.com -> sign in -> **New organization** (Personal, Free) -> **New project**.
2. Name `lost-and-found`, generate and save a database password (the app never uses it), region **Mumbai**.
3. In the Security box: keep **Enable Data API** ticked, untick **Automatically expose new tables** (the schema grants only what the app needs).

## 2. Create the database
1. Left menu -> **SQL Editor** -> **New query**.
2. Paste the whole of `supabase/schema.sql` -> **Run**. A "destructive operations" warning is expected (the file recreates its own policies); choose **Run query**.
3. Success looks like "Success. No rows returned". **Table Editor** now lists `items`, `matches`, `match_settings`.
The file is safe to run again; it never deletes data.

## 3. Sign-in settings
**Authentication -> Sign In / Providers -> Email**
- Demo / testing: turn **Confirm email** OFF. Sign-up then signs the user in immediately. (Supabase's built-in email sender only allows a few emails per hour.)
- Real use: keep it ON and edit **Authentication -> Email Templates -> Confirm signup** so the email contains the 6-digit code `{{ .Token }}` (the app asks for the code). For many users, set up your own SMTP/SES.

## 4. Connect the app
**Project Settings -> API Keys** -> copy the Project URL and the **publishable** key (or the legacy **anon** key) into
`app/src/main/java/com/example/lostandfound/config/BackendConfig.kt`:
```kotlin
const val SUPABASE_URL = "https://<your-project-id>.supabase.co"
const val SUPABASE_ANON_KEY = "sb_publishable_..."
```
Gradle sync, run. While either value is blank the app runs in demo mode with no network.

## 5. Check it works (two phones, or one phone and an emulator)
1. Account A: create an account, report **Lost**: "Black backpack", Bags, Library, description "Black backpack with Dell laptop charger".
2. Account B: report **Found**: "Black laptop bag", Bags, Library, description "bag with a charger inside".
3. Account A sees a match in the Matches tab immediately (within 30 s on account B's side) -> "This is mine" -> both become Claimed -> Mark returned.
4. Different category or no shared word -> no match (false-positive guard).

## 6. Optional
- **Daily clean-up** of old reports: Database -> Extensions -> enable `pg_cron`, then run the commented line at the end of `schema.sql`.
- **Trained scorer:** see `ml/README.md` (one `update` statement).
- **Photos:** stored in a private bucket; no setup needed (created by `schema.sql`).

## Things to know
- Free projects are **paused after about a week without activity**; click Restore in the dashboard (do this before a demo). The free plan has no automatic backups. Check current limits at supabase.com/pricing.
- Matching runs inside the database when a report is saved, so there is no queue to monitor. Look at **Logs** in the dashboard if something fails.

## Troubleshooting
| Symptom | Likely cause |
|---|---|
| App says "demo mode" | URL or key in `BackendConfig.kt` is blank |
| "Please check the details you entered" on sign-up | email format, or password under Supabase's minimum |
| Sign-up asks for a code but none arrives | Confirm email is ON and the template has no `{{ .Token }}`; or the email rate limit was hit |
| "Please sign in again" everywhere | wrong key (must be publishable/anon, not secret), or the session expired |
| Reports save but no matches | need one LOST and one FOUND from different accounts, same category, a shared word, score >= 0.60 |
| Photos missing | signed links expired (they refresh on the next poll), or upload > 5 MB / not JPEG |
