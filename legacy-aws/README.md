# AWS backend

The AWS version of the backend: Cognito, API Gateway, Lambda, DynamoDB, S3, SQS, EventBridge, SES, CloudWatch, CloudFormation.
The app can use it by setting `BACKEND = "aws"` in `BackendConfig.kt` (Supabase, in `../supabase`, is the other option).
Setup steps: [`../docs/DEPLOY_AWS.md`](../docs/DEPLOY_AWS.md). (The folder name is kept from the earlier "legacy" label so existing links keep working.)

```
backend/    CloudFormation template, Lambda code, deploy scripts, 64 tests
extractor/  optional CLIP image-embedding Lambda (container); not needed, photos are compared with Amazon Rekognition labels
```
Run its tests: `cd backend && pip install -r requirements-dev.txt && PYTHONPATH=tests:src python -m unittest discover -s tests`
