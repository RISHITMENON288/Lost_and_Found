#!/usr/bin/env bash
# Manual deploy (the CI pipeline does the same). Needs the AWS CLI configured with credentials.
#   BUDGET_EMAIL=you@example.com SENDER_EMAIL=you@example.com ./deploy.sh
# SENDER_EMAIL must already be verified in Amazon SES (in the SES sandbox, receivers must be verified too).
set -euo pipefail

STACK="${STACK:-campus-lost-found}"
REGION="${AWS_REGION:-us-east-1}"
: "${BUDGET_EMAIL:?Set BUDGET_EMAIL to the address that should receive alarm and budget emails}"

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="${ARTIFACT_BUCKET:-${STACK}-artifacts-${ACCOUNT}}"

if ! aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" >/dev/null   # us-east-1 rejects LocationConstraint
  else
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION" >/dev/null
  fi
  aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
fi

cd "$(dirname "$0")"
aws cloudformation package --template-file template.yaml --s3-bucket "$BUCKET" --output-template-file packaged.yaml --region "$REGION"
aws cloudformation deploy --template-file packaged.yaml --stack-name "$STACK" --region "$REGION" \
  --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset \
  --parameter-overrides BudgetEmail="$BUDGET_EMAIL" SenderEmail="${SENDER_EMAIL:-}" \
    AllowedEmailDomain="${ALLOWED_EMAIL_DOMAIN:-}" ExtractorImageUri="${EXTRACTOR_IMAGE_URI:-}"

# Install the trained matching model where the match worker reads it.
DATA_BUCKET="$(aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" --output text)"
aws s3 cp ../../ml/out/weights_aws.json "s3://${DATA_BUCKET}/models/weights.json" --region "$REGION"

echo
echo "Put these in app/src/main/java/com/example/lostandfound/config/BackendConfig.kt:"
aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'||OutputKey=='Region'||OutputKey=='UserPoolClientId'].[OutputKey,OutputValue]" --output text
