#!/usr/bin/env bash
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
TABLE_NAME="DailyScrum"
ROLE_NAME="DailyScrumLambdaRole"
FUNCTION_NAME="DailyScrumService"

echo "==> Resolving AWS Account ID..."
ACCOUNT_ID=$(aws sts get-caller-identity --query "Account" --output text)

echo "==> 1. Creating DynamoDB Table (PROVISIONED 1 RCU / 1 WCU -> 100% Always Free)..."
if ! aws dynamodb describe-table --table-name "$TABLE_NAME" --region "$REGION" >/dev/null 2>&1; then
    aws dynamodb create-table \
        --table-name "$TABLE_NAME" \
        --attribute-definitions \
            AttributeName=PK,AttributeType=S \
            AttributeName=SK,AttributeType=S \
        --key-schema \
            AttributeName=PK,KeyType=HASH \
            AttributeName=SK,KeyType=RANGE \
        --provisioned-throughput \
            ReadCapacityUnits=1,WriteCapacityUnits=1 \
        --region "$REGION"
    echo "Waiting for DynamoDB table to become ACTIVE..."
    aws dynamodb wait table-exists --table-name "$TABLE_NAME" --region "$REGION"
else
    echo "Table $TABLE_NAME already exists."
fi

echo "==> 2. Creating CloudWatch Log Group with 7-day retention (Safeguard for 5GB Free Tier)..."
aws logs create-log-group --log-group-name "/aws/lambda/$FUNCTION_NAME" --region "$REGION" 2>/dev/null || true
aws logs put-retention-policy \
    --log-group-name "/aws/lambda/$FUNCTION_NAME" \
    --retention-in-days 7 \
    --region "$REGION"

echo "==> 3. Setting up IAM Role..."
cat <<EOF > /tmp/lambda-trust-policy.json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "lambda.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
    aws iam create-role \
        --role-name "$ROLE_NAME" \
        --assume-role-policy-document file:///tmp/lambda-trust-policy.json
    
    aws iam attach-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
    
    cat <<EOF > /tmp/lambda-dynamo-policy.json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
        "dynamodb:Query"
      ],
      "Resource": "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${TABLE_NAME}"
    }
  ]
}
EOF
    aws iam put-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-name "DailyScrumDynamoAccess" \
        --policy-document file:///tmp/lambda-dynamo-policy.json
    
    echo "Waiting for IAM role replication..."
    sleep 10
else
    echo "Role $ROLE_NAME already exists."
fi

echo "==> 4. Packaging Lambda Function (built-in boto3, 0 external deps)..."
zip -j /tmp/daily_scrum_function.zip lambda_function.py

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

echo "==> 5. Creating / Updating Lambda Function..."
if ! aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" >/dev/null 2>&1; then
    aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime python3.11 \
        --role "$ROLE_ARN" \
        --handler lambda_function.handler \
        --zip-file fileb:///tmp/daily_scrum_function.zip \
        --timeout 5 \
        --memory-size 128 \
        --environment "Variables={TABLE_NAME=$TABLE_NAME}" \
        --region "$REGION"
    
    echo "Waiting for Lambda function active state..."
    aws lambda wait function-active-v2 --function-name "$FUNCTION_NAME" --region "$REGION"
else
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file fileb:///tmp/daily_scrum_function.zip \
        --region "$REGION"
fi

echo "==> 6. Configuring Lambda Function URL (CORS enabled, $0 cost)..."
if ! aws lambda get-function-url-config --function-name "$FUNCTION_NAME" --region "$REGION" >/dev/null 2>&1; then
    aws lambda create-function-url-config \
        --function-name "$FUNCTION_NAME" \
        --auth-type NONE \
        --cors '{"AllowOrigins":["*"],"AllowMethods":["GET","POST","PUT","DELETE","OPTIONS"],"AllowHeaders":["Content-Type"]}' \
        --region "$REGION"

    aws lambda add-permission \
        --function-name "$FUNCTION_NAME" \
        --statement-id FunctionURLAllowPublicAccess \
        --action lambda:InvokeFunctionUrl \
        --principal "*" \
        --function-url-auth-type NONE \
        --region "$REGION"
fi

URL=$(aws lambda get-function-url-config --function-name "$FUNCTION_NAME" --query "FunctionUrl" --output text --region "$REGION")

echo ""
echo "=========================================================="
echo " Deployment Complete!"
echo " Lambda Function URL (Always Free Endpoint):"
echo " $URL"
echo "=========================================================="
