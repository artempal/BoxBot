terraform {
  required_providers {
    yandex = {
      source  = "yandex-cloud/yandex"
      version = "~> 0.95.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2.0"
    }
  }
  
  backend "s3" {
    endpoint   = "https://storage.yandexcloud.net"
    bucket     = "boxbot-terraform-state"
    region     = "ru-central1"
    key        = "terraform.tfstate"
    
    skip_region_validation      = true
    skip_credentials_validation = true
    skip_requesting_account_id  = true
    skip_s3_checksum            = true

  }
}

provider "yandex" {
  cloud_id  = var.cloud_id
  folder_id = var.folder_id
  zone      = var.zone
}

# Package the function code before deployment
resource "null_resource" "package_function" {
  triggers = {
    always_run = "${timestamp()}"
  }

  provisioner "local-exec" {
    
    command = <<-EOT
      mkdir -p ../dist
      rm -f ../dist/function.zip
      cd ..
      zip -r dist/function.zip boxbot
      zip -j -r dist/function.zip boxbot/requirements.txt
      zip -d dist/function.zip "**/__pycache__/*" "**/*.pyc" "**/*.pyo" "**/*.pyd" "**/test_*.py" "**/tests/*"
    EOT
  }
}

# Create service account for functions
resource "yandex_iam_service_account" "boxbot_sa" {
  name        = "boxbot-sa"
  description = "Service account for BoxBot"
}

# Grant roles to the service account
resource "yandex_resourcemanager_folder_iam_member" "sa_editor" {
  folder_id = var.folder_id
  role      = "editor"
  member    = "serviceAccount:${yandex_iam_service_account.boxbot_sa.id}"
}

# Create static access key for service account
resource "yandex_iam_service_account_static_access_key" "sa_static_key" {
  service_account_id = yandex_iam_service_account.boxbot_sa.id
  description        = "Static access key for BoxBot SA"
}

resource "yandex_ydb_database_serverless" "boxbot-db" {
  name                = "boxbot-db"
  deletion_protection = true
  
  location_id = "ru-central1"

  serverless_database {
    enable_throttling_rcu_limit = false
    storage_size_limit          = 1
  }
}

# Grant YDB editor role to the service account for the specific database
resource "yandex_ydb_database_iam_binding" "sa_ydb_editor_binding" {
  database_id = yandex_ydb_database_serverless.boxbot-db.id
  role        = "ydb.editor"
  members = [
    "serviceAccount:${yandex_iam_service_account.boxbot_sa.id}"
  ]
}

# Create Cloud Function (Lambda replacement)
resource "yandex_function" "boxbot_function" {
  name               = "boxbot-function"
  description        = "BoxBot Telegram webhook handler"
  user_hash          = uuid()
  runtime            = "python39"
  entrypoint         = "boxbot.lambda.handler.handler"
  memory             = "128"
  execution_timeout  = "30"
  service_account_id = yandex_iam_service_account.boxbot_sa.id
  
  environment = {
    TELEGRAM_TOKEN       = var.telegram_token
    ALLOWED_USERS        = var.allowed_users
    YDB_ENDPOINT         = yandex_ydb_database_serverless.boxbot-db.document_api_endpoint
    YDB_DATABASE         = yandex_ydb_database_serverless.boxbot-db.database_path
    DYNAMODB_TABLE       = "boxbot_table"
    DEPLOYMENT_MODE      = "production"
    # Add AWS credentials for DynamoDB API compatibility
    AWS_ACCESS_KEY_ID     = yandex_iam_service_account_static_access_key.sa_static_key.access_key
    AWS_SECRET_ACCESS_KEY = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
    AWS_DEFAULT_REGION    = "ru-central1"
    # Add DynamoDB endpoint URL for YDB
    DYNAMODB_ENDPOINT     = yandex_ydb_database_serverless.boxbot-db.document_api_endpoint
  }
  
  content {
    zip_filename = var.function_package_path
  }
  
  depends_on = [null_resource.package_function]
}

# Create API Gateway (API Gateway replacement)
resource "yandex_api_gateway" "boxbot_gateway" {
  name        = "boxbot-gateway"
  description = "API Gateway for BoxBot"
  
  spec = <<-EOT
    openapi: 3.0.0
    info:
      title: BoxBot API
      version: 1.0.0
    paths:
      /webhook:
        post:
          x-yc-apigateway-integration:
            type: cloud_functions
            functionId: ${yandex_function.boxbot_function.id}
            service_account_id: ${yandex_iam_service_account.boxbot_sa.id}
          operationId: handleWebhook
  EOT
}

# Output important information
output "api_gateway_url" {
  value = "https://${yandex_api_gateway.boxbot_gateway.domain}/webhook"
  description = "API Gateway URL for Telegram webhook"
}

output "function_id" {
  value = yandex_function.boxbot_function.id
  description = "Function ID"
}

output "ydb_endpoint" {
  value = yandex_ydb_database_serverless.boxbot-db.document_api_endpoint
  description = "YDB Endpoint"
} 
