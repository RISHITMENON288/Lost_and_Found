# Architecture (viva notes)

## Diagram
```
 Android app (Kotlin / Jetpack Compose)
   |  Supabase Auth (HTTPS): sign up, optional email code, sign in, refresh      -> access token (kept in memory)
   |  Supabase API (HTTPS) with  apikey = publishable key  +  Authorization = user's access token
   v
 PostgREST (Data API)  --- Row Level Security decides every read, no server code to forget a check
   |-- items   (INSERT only, limited columns)      BEFORE INSERT trigger: validate, set reporter, limit 20 open
   |                                               AFTER  INSERT trigger: run matching  -> matches (PENDING)
   |-- matches (read only for the two people involved)
   |-- rpc: close_item / mark_returned / respond_to_match   (SECURITY DEFINER, check ownership inside)
   '-- Storage: private bucket "item-photos" (JPEG, 5 MB, own folder, write-once, read via signed link)
 App polls every 30 s -> local notification when a new PENDING match appears
```

## Why these choices
| Decision | Reason |
|---|---|
| Two backends behind one interface | The app talks to `AuthRepository` / `ItemRepository`; `BackendConfig.BACKEND` picks AWS (`legacy-aws/backend`, `docs/DEPLOY_AWS.md`) or Supabase (`supabase/`). Same rules in both: the finder's phone is released only to the owner, after confirming |
| Rules enforced in the database (RLS + functions) | The app holds a public key, so the client cannot be trusted; the database is the only trusted place |
| Matching in SQL, triggered on insert | Runs in the same transaction as the report: no queue, no polling worker, nothing to retry. Cost: it is limited to a few hundred candidates per report, fine for a campus |
| Matches created only by the matcher | Users cannot forge or edit a match; they can only accept or reject their own |
| Python reference + parity test | `ml/lf_matcher.py` is used for training; a test proves SQL gives identical scores |
| Polling + local notifications | Push (FCM) needs Firebase setup; limitation: no alert when the app is closed |
| Tokens in memory only | Safer; cost: sign in again after the app process dies |
| No Edge Functions, no queues, no extra services | Nothing here needs them |

## Data model
- **items**: id, reporter_id, reporter_name, type LOST|FOUND, category, title, description, location, occurred_at (ms), image_path, status, created_at (ms).
- **matches**: id, lost_item_id, found_item_id, both reporter ids, score, state PENDING|CONFIRMED|REJECTED. Unique per pair, so a pair is never suggested twice and a rejected pair is never resurrected.
- **match_settings**: optional trained model (JSON). Not readable by app users.

## Lifecycle
Item: `OPEN -> POTENTIAL_MATCH -> CLAIMED -> RETURNED`, or `CLOSED` by the owner (or the clean-up job).
Match: `PENDING -> CONFIRMED | REJECTED`. Only the owner of the lost item decides. Confirming one match rejects the competing suggestions.

## Matching (false positives matter most)
Hard gates, any failure = score 0: one LOST + one FOUND, same category, found not more than 1 day before lost, at least one shared word, different reporters.
Score: `0.20 + 0.45*text + 0.20*location + 0.15*time`, suggested at >= 0.60. Nothing is assigned automatically. An optional logistic model (trained in `ml/`, threshold chosen for 95% precision on a validation split) can replace the weights. Photo similarity: the Supabase version does not use photos. The AWS version asks Amazon Rekognition for object labels of each photo (once, in the match worker) and uses the label overlap as an extra input; its two weights are hand-set because there are no real photo pairs to learn from.

## Security
- RLS on every table; API roles have only the privileges listed in `schema.sql` (clients can INSERT six columns of `items` and SELECT; nothing else).
- Reporter identity, status and timestamps are set by the database, never taken from the client.
- Inputs validated in the database (lengths, allowed locations/categories, time window, control characters removed, photo path must be in the user's own folder and exist).
- Photos: private bucket, JPEG only, 5 MB, write-once, readable only for reports the user may see; the app re-encodes to JPEG (strips EXIF/GPS).
- App: HTTPS only, no redirects, response size cap, generic error messages (only messages written by us are shown).
- Secrets: the app contains only the public URL and publishable key. gitleaks runs in CI.

## Testing map
| Level | What | Where |
|---|---|---|
| Database / security | 23 tests on real Postgres: users cannot read, forge or edit each other's data; validation; lifecycle; photo access; SQL vs Python scoring | `supabase/tests` |
| Unit (Android) | Kotlin matcher (demo mode), error mapping | `app/src/test` |
| ML | held-out precision/recall/FP/FN vs default weights | `ml/out/report.md` |
| Security scan | ruff, bandit, pip-audit, gitleaks | CI |
| Acceptance | two-account demo script | `docs/DEPLOY.md` step 5 |

## Known limitations
- No push when the app is closed; no admin/moderation screen.
- ML numbers in the repo are from synthetic data; real accuracy needs real labelled pairs.
- The tests emulate Supabase's auth/storage on plain Postgres; the real project and the Compose UI were not exercised by the author's tooling. Run the acceptance script and report anything that differs.
- Free-plan projects pause after inactivity and have no automatic backups.

## Phone numbers (contact after a confirmed match)

- The sign-up screen asks for a mobile number and sends it as sign-up metadata. A database trigger copies a valid number into `public.profiles`, a table no app user can read directly (no table privileges, row level security on).
- The only way to read a number is `get_match_contact(match_id)`. It returns the **finder's** number to the **owner of the lost item**, only after the owner confirmed the match and until the item is returned. The finder never sees the owner's number; strangers get nothing.
- Reporting a FOUND item requires an account with a phone number, so a confirmed match can always be followed up.
- Numbers are not verified by SMS (that costs money); this is a known limitation.
