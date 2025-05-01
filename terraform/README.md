# BoxBot Terraform Deployment

This directory contains Terraform configuration files for deploying BoxBot on Yandex Cloud.

## Prerequisites

- [Terraform](https://www.terraform.io/downloads.html) (v1.0.0+)
- [Yandex Cloud CLI](https://cloud.yandex.com/en/docs/cli/quickstart)
- [AWS CLI](https://aws.amazon.com/cli/) (for S3 backend configuration)

## Initial Setup

Install yc cli https://yandex.cloud/ru/docs/cli/quickstart
Install terraform https://yandex.cloud/ru/docs/tutorials/infrastructure-management/terraform-quickstart

1. First, set up the Terraform backend (Yandex Object Storage bucket):

```bash
yc init
export PATH=$PATH:/opt/terraform
export YC_TOKEN=$(yc iam create-token)
export YC_CLOUD_ID=$(yc config get cloud-id)
export YC_FOLDER_ID=$(yc config get folder-id)
apt-get install jq
chmod +x ../scripts/setup_terraform_backend.sh
../scripts/setup_terraform_backend.sh
```

2. Copy `terraform.tfvars.example` to `terraform.tfvars` and fill in your values:

```bash
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your values
```

## Deployment

1. Initialize Terraform:
nano ~/.terraformrc

```bash
terraform init \
  -backend-config="access_key=$YC_ACCESS_KEY_ID" \
  -backend-config="secret_key=$YC_SECRET_ACCESS_KEY"
```

2. Preview the changes:

```bash
terraform plan
```

3. Apply the changes:

```bash
terraform apply
```

4. After successful deployment, set up the Telegram webhook:

```bash
TELEGRAM_TOKEN=
API_GATEWAY_URL=$(terraform output -raw api_gateway_url)
curl -X POST https://api.telegram.org/bot$TELEGRAM_TOKEN/setWebhook -d "url=${API_GATEWAY_URL}"
```

## GitHub Actions Deployment

For GitHub Actions deployment, you need to add the following secrets to your GitHub repository:

- `YC_CLOUD_ID`: Your Yandex Cloud ID
- `YC_FOLDER_ID`: Your Yandex Cloud Folder ID
- `YC_ACCESS_KEY_ID`: Access key for Yandex Object Storage
- `YC_SECRET_ACCESS_KEY`: Secret key for Yandex Object Storage
- `TELEGRAM_TOKEN`: Your Telegram bot token
- `ALLOWED_USERS`: Comma-separated list of allowed Telegram user IDs

The GitHub Actions workflow will automatically deploy your application when you push to the main branch.

## Customization

- Modify `main.tf` to adjust the infrastructure resources
- Modify `variables.tf` to add or remove variables
- Update environment variables in the Cloud Function resource as needed 