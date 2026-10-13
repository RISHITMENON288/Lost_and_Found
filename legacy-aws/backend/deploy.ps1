# Manual deploy for Windows PowerShell (the CI pipeline does the same). Needs the AWS CLI configured.
#   .\deploy.ps1 -BudgetEmail you@example.com -SenderEmail you@example.com
# SenderEmail must already be verified in Amazon SES (in the SES sandbox, receivers must be verified too).
param(
    [Parameter(Mandatory = $true)][string]$BudgetEmail,
    [string]$SenderEmail = "",
    [string]$Stack = "campus-lost-found",
    [string]$Region = "us-east-1",
    [string]$AllowedEmailDomain = "",
    [string]$ExtractorImageUri = ""
)
$ErrorActionPreference = "Stop"

$account = aws sts get-caller-identity --query Account --output text
$bucket = "$Stack-artifacts-$account"

# Windows PowerShell 5.1 turns native stderr into a terminating error under "Stop", so relax it for this probe.
$ErrorActionPreference = "Continue"
aws s3api head-bucket --bucket $bucket 2>$null
$bucketMissing = ($LASTEXITCODE -ne 0)
$ErrorActionPreference = "Stop"
if ($bucketMissing) {
    if ($Region -eq "us-east-1") {
        aws s3api create-bucket --bucket $bucket --region $Region | Out-Null   # us-east-1 rejects LocationConstraint
    } else {
        aws s3api create-bucket --bucket $bucket --region $Region --create-bucket-configuration LocationConstraint=$Region | Out-Null
    }
    aws s3api put-public-access-block --bucket $bucket --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
}

Set-Location $PSScriptRoot
aws cloudformation package --template-file template.yaml --s3-bucket $bucket --output-template-file packaged.yaml --region $Region
aws cloudformation deploy --template-file packaged.yaml --stack-name $Stack --region $Region `
    --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset `
    --parameter-overrides "BudgetEmail=$BudgetEmail" "SenderEmail=$SenderEmail" "AllowedEmailDomain=$AllowedEmailDomain" "ExtractorImageUri=$ExtractorImageUri"

# Install the trained matching model where the match worker reads it.
$dataBucket = aws cloudformation describe-stacks --stack-name $Stack --region $Region `
    --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" --output text
aws s3 cp "..\..\ml\out\weights_aws.json" "s3://$dataBucket/models/weights.json" --region $Region

Write-Host "`nPut these in app\src\main\java\com\example\lostandfound\config\BackendConfig.kt:"
aws cloudformation describe-stacks --stack-name $Stack --region $Region `
    --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'||OutputKey=='Region'||OutputKey=='UserPoolClientId'].[OutputKey,OutputValue]" --output text
