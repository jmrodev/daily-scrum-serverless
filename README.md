# Daily Scrum Serverless (Always Free)

A lightweight, zero-cost serverless Daily Scrum tracker built with AWS Lambda, DynamoDB, and GitHub Pages.

## Architecture

- **Frontend:** Static HTML/JS hosted on **GitHub Pages** (Client-Side Rendering).
- **Backend:** **AWS Lambda** exposed via **Lambda Function URL** (no API Gateway fees).
- **Database:** **Amazon DynamoDB** in Provisioned mode (1 RCU / 1 WCU) within the permanent Free Tier.
- **Monitoring:** CloudWatch Logs configured with a 7-day retention policy to prevent storage accumulation.

## Deployment

### 1. Backend (AWS)

Ensure your AWS CLI credentials are set up, then run:

```bash
chmod +x deploy.sh
./deploy.sh
```

The script will output your **Lambda Function URL**.

### 2. Frontend (GitHub Pages)

1. Open the published GitHub Pages URL (or `index.html` locally).
2. Enter your Lambda Function URL in the configuration box.
3. Submit and load Daily Scrum updates directly.
