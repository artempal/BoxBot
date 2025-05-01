#!/bin/bash
set -e


echo "Creating Yandex Object Storage bucket for Terraform state..."

# Create a service account for managing the bucket
echo "Creating service account for Terraform backend..."
SA_ID=$(yc iam service-account create --name terraform-backend-sa \
  --description "Service account for Terraform backend storage" \
  --format json | jq -r '.id')

echo "Service account created with ID: $SA_ID"

# Grant necessary permissions to the service account
echo "Granting permissions to the service account..."
yc resource-manager folder add-access-binding --id $YC_FOLDER_ID \
  --role storage.admin \
  --subject serviceAccount:$SA_ID

# Create static access keys for the service account
echo "Creating static access keys for the service account..."
KEYS=$(yc iam access-key create --service-account-id $SA_ID --format json)
ACCESS_KEY=$(echo $KEYS | jq -r '.access_key.key_id')
SECRET_KEY=$(echo $KEYS | jq -r '.secret')

echo "Keys created. Access key: $ACCESS_KEY"

# Create the S3 bucket for Terraform state
echo "Creating S3 bucket for Terraform state..."
yc storage bucket create --name boxbot-terraform-state

echo "Bucket created successfully."

# Display instructions for using the backend
echo ""
echo "Terraform backend is set up. Use the following environment variables for GitHub Secrets:"
echo ""
echo "YC_ACCESS_KEY_ID=$ACCESS_KEY"
echo "YC_SECRET_ACCESS_KEY=$SECRET_KEY"
echo ""
echo "Also make sure to set:"
echo "YC_CLOUD_ID - Your Yandex Cloud ID"
echo "YC_FOLDER_ID - Your folder ID"
echo "TELEGRAM_TOKEN - Your Telegram bot token"
echo "ALLOWED_USERS - Comma-separated list of allowed Telegram user IDs" 