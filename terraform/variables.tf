variable "cloud_id" {
  description = "Yandex Cloud ID"
  type        = string
}

variable "folder_id" {
  description = "Yandex Cloud Folder ID"
  type        = string
}

variable "zone" {
  description = "Yandex Cloud Zone"
  type        = string
  default     = "ru-central1-a"
}

variable "telegram_token" {
  description = "Telegram Bot Token"
  type        = string
  sensitive   = true
}

variable "allowed_users" {
  description = "Comma-separated list of allowed Telegram user IDs"
  type        = string
  default     = ""
}

variable "function_package_path" {
  description = "Path to the ZIP file with the function code"
  type        = string
  default     = "../dist/function.zip"
} 