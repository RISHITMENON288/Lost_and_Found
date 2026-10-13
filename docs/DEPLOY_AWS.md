# Setting up the backend on AWS

Use this if `BackendConfig.BACKEND` is `"aws"`. The Supabase steps are in `DEPLOY.md`; the app can use either.
Everything is created by one CloudFormation stack from `legacy-aws/backend/template.yaml`:
Cognito (login), API Gateway + Lambda (API), DynamoDB (data), S3 (photos + the trained model), SQS (matching queue),
EventBridge (expiry), Rekognition (photo labels), SES (emails), SNS + CloudWatch (alarms), IAM (roles), Budgets (cost alert).

> **Never put an AWS access key in the app, in GitHub, or in a chat.** The app only gets three public values (step 5).

## What it costs
Light use stays inside the free tier or a few cents. Rekognition costs about $0.001 per photo after its free tier (5,000 images a month for the first 12 months). The stack sets a monthly budget alert (`MonthlyBudgetUsd`, default 5).
Delete the stack when the project is over (step 8).

## 1. Tools (once, on your PC)
1. Install the **AWS CLI v2** (aws.amazon.com/cli). Open a new PowerShell and check `aws --version`.
2. In the AWS console -> **IAM -> Users -> lf-deploy -> Security credentials -> Create access key** (use case: CLI).
   Copy both values; you will not see the secret again.
3. `aws configure` -> paste the key id and secret, region `us-east-1`, output `json`.
   The user needs permission to create the stack's resources. For this short deploy, `AdministratorAccess` is the simplest; remove it afterwards.

## 2. Verify the sender email in SES
**SES -> Configuration -> Identities** (region N. Virginia) -> your sender address must show **Verified**.
In the SES sandbox, every *receiving* address must be verified too (your own two test emails).
Without a sender the app still works; it just sends no emails.

## 3. Deploy
```powershell
cd legacy-aws\backend
.\deploy.ps1 -BudgetEmail you@gmail.com -SenderEmail you@gmail.com
```
Takes about 5 minutes. It also uploads `ml/out/weights_aws.json` to `models/weights.json` in the stack's bucket (the trained model plus the hand-set photo weights; build it with `python ml/make_aws_model.py`).
Mac/Linux: `BUDGET_EMAIL=... SENDER_EMAIL=... ./deploy.sh`.
Open the **"confirm subscription"** email from AWS SNS (alarms) and click confirm.

## 4. Print the three app values
The script prints `ApiUrl`, `Region`, `UserPoolClientId` at the end.

## 5. Connect the app
In `app/src/main/java/com/example/lostandfound/config/BackendConfig.kt`:
```kotlin
const val BACKEND = "aws"
const val AWS_API_URL = "https://xxxx.execute-api.us-east-1.amazonaws.com"
const val AWS_REGION = "us-east-1"
const val COGNITO_CLIENT_ID = "xxxxxxxxxxxxxxxxxxxxxxxxxx"
```
Gradle sync, run. While these are blank the app falls back to demo mode.

## 6. Check it works (two accounts)
1. Account A signs up -> Cognito emails a 6-digit code -> enter it -> sign in.
2. A reports **Lost**: "Black backpack", Bags, Library, description "Black backpack with Dell laptop charger".
3. Account B reports **Found**: "Black laptop bag", Bags, Library, description "bag with a charger inside", with a phone number set at sign-up.
4. Within a minute A gets a match in the Matches tab and an email (to a verified address). A taps "This is mine" -> B gets an email -> A can tap **Show phone number**.
5. Different category or no shared word -> no match.
6. Photos: when both reports have a photo, Rekognition's labels (like "backpack") are compared and raise the score; two unrelated photos lower it.

## 7. If something fails
| Symptom | Likely cause |
|---|---|
| Deploy fails on the first run | read the red event in **CloudFormation -> Stacks -> campus-lost-found -> Events**; fix and run the script again |
| App says "demo mode" | one of the three values in `BackendConfig.kt` is blank, or `BACKEND` is not `"aws"` |
| "Please sign in again" everywhere | wrong `COGNITO_CLIENT_ID`, or the API from a different stack |
| Sign-up works but no code email | check spam; Cognito's built-in sender allows about 50 emails a day |
| Matches appear but no emails | `SenderEmail` not verified, or the receiver is not verified (SES sandbox). See **CloudWatch -> Logs -> /aws/lambda/campus-lost-found-match-worker** ("Email not sent: MessageRejected") |
| Reports save but no matches | need one LOST and one FOUND from different accounts, same category, a shared word; the model must be at `models/weights.json` |
| Phone number "not available" | the finder left no phone at sign-up, or the item was already marked returned |

## 8. Clean up
- **IAM -> Users -> lf-deploy -> Security credentials -> delete the access key** (and remove `AdministratorAccess`).
- End of project: empty the stack's bucket, then **CloudFormation -> delete stack**. Delete the old hand-made services (`lf-api`, `lf-lambda-role`, hand-made Cognito pool, S3/SNS) that the stack replaces.

## Things to know
- The phone number is a normal Cognito attribute and is **not SMS-verified** (a user can type someone else's number).
- Emails never contain phone numbers; the number is released by the API only to the owner of the lost item, after confirming, until the item is returned.
- Photos are not compared pixel by pixel: only Rekognition's object labels are. The photo weights are hand-set, not learned.
- Photos are private in S3 and shown through links that expire after an hour.
