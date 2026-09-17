#!/usr/bin/env bash
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
TABLE_NAME="DailyScrum"
ROLE_NAME="DailyScrumLambdaRole"
FUNCTION_NAME="DailyScrumService"
USER_POOL_NAME="DailyScrumUserPool"
CLIENT_NAME="DailyScrumWebClient"

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

echo "==> 2. Setting up Amazon Cognito User Pool (50,000 MAUs Always Free)..."
USER_POOL_ID=$(aws cognito-idp list-user-pools --max-results 60 --region "$REGION" --query "UserPools[?Name=='$USER_POOL_NAME'].Id" --output text 2>/dev/null || true)

if [ -z "$USER_POOL_ID" ] || [ "$USER_POOL_ID" = "None" ]; then
    USER_POOL_ID=$(aws cognito-idp create-user-pool \
        --pool-name "$USER_POOL_NAME" \
        --auto-verified-attributes email \
        --username-attributes email \
        --policies '{"PasswordPolicy":{"MinimumLength":8,"RequireUppercase":true,"RequireLowercase":true,"RequireNumbers":true,"RequireSymbols":false}}' \
        --region "$REGION" \
        --query "UserPool.Id" --output text)
    echo "Created Cognito User Pool: $USER_POOL_ID"
else
    echo "Cognito User Pool $USER_POOL_NAME already exists: $USER_POOL_ID"
fi

echo "==> 3. Setting up Cognito App Client (Public SPA - No Secret)..."
CLIENT_ID=$(aws cognito-idp list-user-pool-clients --user-pool-id "$USER_POOL_ID" --region "$REGION" --query "UserPoolClients[?ClientName=='$CLIENT_NAME'].ClientId" --output text 2>/dev/null || true)

if [ -z "$CLIENT_ID" ] || [ "$CLIENT_ID" = "None" ]; then
    CLIENT_ID=$(aws cognito-idp create-user-pool-client \
        --user-pool-id "$USER_POOL_ID" \
        --client-name "$CLIENT_NAME" \
        --no-generate-secret \
        --explicit-auth-flows ALLOW_USER_PASSWORD_AUTH ALLOW_USER_SRP_AUTH ALLOW_REFRESH_TOKEN_AUTH \
        --region "$REGION" \
        --query "UserPoolClient.ClientId" --output text)
    echo "Created Cognito App Client: $CLIENT_ID"
else
    echo "Cognito App Client $CLIENT_NAME already exists: $CLIENT_ID"
fi

echo "==> 4. Setting up Cognito Groups (Admins and Members)..."
for GROUP in Admins Members; do
    if ! aws cognito-idp get-group --user-pool-id "$USER_POOL_ID" --group-name "$GROUP" --region "$REGION" >/dev/null 2>&1; then
        aws cognito-idp create-group --user-pool-id "$USER_POOL_ID" --group-name "$GROUP" --region "$REGION"
        echo "Created Cognito Group: $GROUP"
    else
        echo "Cognito Group $GROUP already exists."
    fi
done

echo "==> 5. Creating CloudWatch Log Group with 7-day retention (Safeguard for 5GB Free Tier)..."
aws logs create-log-group --log-group-name "/aws/lambda/$FUNCTION_NAME" --region "$REGION" 2>/dev/null || true
aws logs put-retention-policy \
    --log-group-name "/aws/lambda/$FUNCTION_NAME" \
    --retention-in-days 7 \
    --region "$REGION"

echo "==> 6. Setting up IAM Role..."
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
    
    echo "Waiting for IAM role creation..."
    sleep 5
else
    echo "Role $ROLE_NAME already exists."
fi

cat <<EOF > /tmp/lambda-app-policy.json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DynamoDBAccess",
      "Effect": "Allow",
      "Action": [
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
        "dynamodb:Query",
        "dynamodb:Scan"
      ],
      "Resource": "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${TABLE_NAME}"
    },
    {
      "Sid": "CognitoAuthAccess",
      "Effect": "Allow",
      "Action": [
        "cognito-idp:SignUp",
        "cognito-idp:ConfirmSignUp",
        "cognito-idp:InitiateAuth",
        "cognito-idp:GetUser",
        "cognito-idp:AdminAddUserToGroup",
        "cognito-idp:AdminListGroupsForUser",
        "cognito-idp:ListUsers"
      ],
      "Resource": "arn:aws:cognito-idp:${REGION}:${ACCOUNT_ID}:userpool/${USER_POOL_ID}"
    }
  ]
}
EOF

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "DailyScrumAppAccess" \
    --policy-document file:///tmp/lambda-app-policy.json

echo "==> 7. Packaging Lambda Function (built-in boto3, 0 external deps)..."
zip -j /tmp/daily_scrum_function.zip lambda_function.py

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

echo "==> 8. Creating / Updating Lambda Function..."
ENV_VARS="Variables={TABLE_NAME=$TABLE_NAME,USER_POOL_ID=$USER_POOL_ID,CLIENT_ID=$CLIENT_ID,AWS_REGION=$REGION}"

if ! aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" >/dev/null 2>&1; then
    aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime python3.11 \
        --role "$ROLE_ARN" \
        --handler lambda_function.handler \
        --zip-file fileb:///tmp/daily_scrum_function.zip \
        --timeout 8 \
        --memory-size 128 \
        --environment "$ENV_VARS" \
        --region "$REGION"
    
    echo "Waiting for Lambda function active state..."
    aws lambda wait function-active-v2 --function-name "$FUNCTION_NAME" --region "$REGION"
else
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file fileb:///tmp/daily_scrum_function.zip \
        --region "$REGION"
    
    aws lambda update-function-configuration \
        --function-name "$FUNCTION_NAME" \
        --environment "$ENV_VARS" \
        --timeout 8 \
        --region "$REGION" >/dev/null
fi

echo "==> 9. Configuring Lambda Function URL (CORS enabled with Authorization header)..."
if ! aws lambda get-function-url-config --function-name "$FUNCTION_NAME" --region "$REGION" >/dev/null 2>&1; then
    aws lambda create-function-url-config \
        --function-name "$FUNCTION_NAME" \
        --auth-type NONE \
        --cors '{"AllowOrigins":["*"],"AllowMethods":["GET","POST","PUT","DELETE","OPTIONS"],"AllowHeaders":["Content-Type","Authorization"]}' \
        --region "$REGION"

    aws lambda add-permission \
        --function-name "$FUNCTION_NAME" \
        --statement-id FunctionURLAllowPublicAccess \
        --action lambda:InvokeFunctionUrl \
        --principal "*" \
        --function-url-auth-type NONE \
        --region "$REGION"
else
    aws lambda update-function-url-config \
        --function-name "$FUNCTION_NAME" \
        --cors '{"AllowOrigins":["*"],"AllowMethods":["GET","POST","PUT","DELETE","OPTIONS"],"AllowHeaders":["Content-Type","Authorization"]}' \
        --region "$REGION" >/dev/null || true
fi

URL=$(aws lambda get-function-url-config --function-name "$FUNCTION_NAME" --query "FunctionUrl" --output text --region "$REGION")

echo ""
echo "=========================================================="
echo " Deployment Complete!"
echo " Lambda Function URL (Always Free Endpoint):"
echo " $URL"
echo ""
echo " Cognito User Pool ID: $USER_POOL_ID"
echo " Cognito Client ID:    $CLIENT_ID"
echo " Region:               $REGION"
echo "=========================================================="
