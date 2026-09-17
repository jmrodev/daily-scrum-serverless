# Deployment Script Reference (`deploy.sh`)

This document details the operational mechanics, security configuration, and idempotency safeguards implemented in [`deploy.sh`](../deploy.sh).

---

## 1. Design Principles

* **Strict Bash Execution:** Configured with `set -euo pipefail` to ensure immediate termination upon any unhandled command failure or undefined variable.
* **Idempotency:** Every cloud resource creation checks for prior existence before attempting provisioning, allowing safe, repeated executions.
* **Zero Hardcoded Secrets:** Automatically resolves the caller's AWS Account ID via `aws sts get-caller-identity`.

---

## 2. Step-by-Step Execution Lifecycle

### Step 1: Account Resolution
```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query "Account" --output text)
```
Retrieves the 12-digit AWS account number from the active credentials session.

### Step 2: DynamoDB Provisioning
```bash
aws dynamodb create-table \
    --table-name DailyScrum \
    --attribute-definitions AttributeName=PK,AttributeType=S AttributeName=SK,AttributeType=S \
    --key-schema AttributeName=PK,KeyType=HASH AttributeName=SK,KeyType=RANGE \
    --provisioned-throughput ReadCapacityUnits=1,WriteCapacityUnits=1
aws dynamodb wait table-exists --table-name DailyScrum
```
* Uses `wait table-exists` to halt script progression until the table status transitions to `ACTIVE`.

### Step 3: CloudWatch Log Group & Retention
```bash
aws logs create-log-group --log-group-name "/aws/lambda/DailyScrumService"
aws logs put-retention-policy --log-group-name "/aws/lambda/DailyScrumService" --retention-in-days 7
```
* Explicitly sets a **7-day expiration** to safeguard the 5 GB Free Tier limit.

### Step 4: IAM Role & Least Privilege Policies
1. **Trust Policy:** Allows `lambda.amazonaws.com` to assume the role.
2. **AWSLambdaBasicExecutionRole:** Attaches the AWS-managed policy for CloudWatch log stream creation.
3. **Inline Policy (`DailyScrumDynamoAccess`):**
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": [
           "dynamodb:PutItem",
           "dynamodb:GetItem",
           "dynamodb:UpdateItem",
           "dynamodb:Query"
         ],
         "Resource": "arn:aws:dynamodb:us-east-1:<ACCOUNT_ID>:table/DailyScrum"
       }
     ]
   }
   ```
   Strictly confines DynamoDB permissions to the `DailyScrum` table resource ARN.

### Step 5: Packaging & Lambda Deployment
* Compresses `lambda_function.py` into a temporary zip.
* Creates the function if new, or runs `aws lambda update-function-code` if it already exists.

### Step 6: Public Function URL & CORS
* Provisions the Function URL with `AuthType: NONE`.
* Establishes resource-based permission:
  ```bash
  aws lambda add-permission \
      --function-name DailyScrumService \
      --statement-id FunctionURLAllowPublicAccess \
      --action lambda:InvokeFunctionUrl \
      --principal "*" \
      --function-url-auth-type NONE
  ```
* Displays the final endpoint URL.
