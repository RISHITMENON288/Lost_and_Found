# Campus Lost & Found

Android app (Kotlin + Jetpack Compose) with a choice of backend: AWS or Supabase. Students report **lost** or **found** items; the system suggests likely matches and notifies the owner, who must confirm. Nothing is ever assigned automatically, and the matcher is tuned to avoid false positives.

```
app/          Android app (demo mode with an in-memory mock, or real Supabase when BackendConfig is filled)
supabase/     schema.sql (tables, security rules, matching, photo storage) + tests on real Postgres
ml/           training of the optional match scorer, synthetic data generator, evaluation report
docs/         DEPLOY.md (setup), ARCHITECTURE.md (design + viva notes)
legacy-aws/   the AWS backend (CloudFormation + Lambda), selectable with BackendConfig.BACKEND = "aws"
.github/      CI: lint, database tests, ML smoke test, security scans, Android build
```

## Run the app right now (no backend)
Open the folder in Android Studio, sync Gradle, run. With `config/BackendConfig.kt` blank the app runs in **demo mode**: sign in with any valid email and an 8+ character password, report a lost "Black backpack" (Bags, Library); a seeded found item matches it.

## Run it for real
AWS: follow [`docs/DEPLOY_AWS.md`](docs/DEPLOY_AWS.md) (one CloudFormation stack, then paste three values into `BackendConfig.kt` and set `BACKEND = "aws"`).
Supabase: follow [`docs/DEPLOY.md`](docs/DEPLOY.md): create a free Supabase project, paste `supabase/schema.sql` into the SQL Editor, paste the project URL and publishable key into `BackendConfig.kt`.

## Matching in one paragraph
Score is 0 unless the pair is one LOST + one FOUND from different people, same category, found not >1 day before lost, with at least one shared word. Otherwise a weighted mix of text similarity, location and time; suggested only at >= 0.60. Details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Evaluation method: [`ml/README.md`](ml/README.md).

## Tests
```bash
./gradlew testDebugUnitTest lintDebug                        # Android
pip install "psycopg[binary]" -r ml/requirements.txt
LF_TEST_DSN=postgresql://postgres:<pw>@localhost:5432/postgres python -m unittest discover -s supabase/tests -v   # needs any Postgres 15+
```

## Honest status
- Verified by running: the database file (23 tests: access rules, matching, lifecycle), SQL-vs-Python scoring parity, the ML pipeline, and a compile + unit-test run of the app's non-UI Kotlin code.
- AWS backend: 64 Python tests (rules, phone privacy, emails, photo labels, handlers) pass with an in-memory fake of DynamoDB/S3/SQS/SES; the template passes cfn-lint.
- Not verified: the full Android UI build, a real AWS deployment, real SES emails and the live Supabase project from the app. Expect small fixes on first run.
- ML metrics in the repo come from synthetic data and only prove the pipeline works.
- No push notifications when the app is closed (polling + local notifications).
