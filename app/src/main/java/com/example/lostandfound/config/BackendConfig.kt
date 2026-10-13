package com.example.lostandfound.config

/**
 * Where the app finds its backend. Every value here is a PUBLIC identifier made to be shipped inside an app:
 * what a signed-in user may read or change is enforced by the server (Row Level Security on Supabase, the
 * Cognito login plus the Lambda code on AWS), not by keeping these secret.
 *
 * NEVER put a secret here: not Supabase's "service_role" key and not an AWS access key.
 *
 * BACKEND picks the server: "aws" or "supabase". While the chosen one is not filled in, the app runs in DEMO
 * mode with an in-memory mock backend.
 */
object BackendConfig {
    /** "aws" = Cognito + API Gateway + Lambda + DynamoDB + S3 (backend in legacy-aws/backend). "supabase" = the older backend. */
    const val BACKEND = "aws"

    // ---- AWS: the three values printed by deploy.sh / deploy.ps1 at the end ----
    /** ApiUrl, e.g. "https://abc123.execute-api.us-east-1.amazonaws.com". */
    const val AWS_API_URL = "https://c2l4gv8zlh.execute-api.us-east-1.amazonaws.com"

    /** Region, e.g. "us-east-1". */
    const val AWS_REGION = "us-east-1"

    /** UserPoolClientId (the app client; it has no secret). */
    const val COGNITO_CLIENT_ID = "3pl88l0cgfeo67iksih9dd6jvj"

    // ---- Supabase ----
    /** Supabase dashboard -> Project Settings -> API -> Project URL, e.g. "https://abcdxyz.supabase.co". */
    const val SUPABASE_URL = "https://xnpchubfavaexcqnaxvv.supabase.co"

    /** Supabase dashboard -> Project Settings -> API Keys -> the "anon" / "publishable" key. */
    const val SUPABASE_ANON_KEY = "sb_publishable_NCYciKrDKuSdHbdoxrH3yQ_b-riP3Bt"

    val useAws: Boolean
        get() = BACKEND == "aws" && AWS_API_URL.startsWith("https://") && AWS_REGION.isNotBlank() && COGNITO_CLIENT_ID.isNotBlank()

    private val useSupabase: Boolean
        get() = BACKEND != "aws" && SUPABASE_URL.startsWith("https://") && SUPABASE_ANON_KEY.isNotBlank()

    /** True when a real backend is chosen and filled in; false means demo mode. */
    val isConfigured: Boolean
        get() = useAws || useSupabase
}
