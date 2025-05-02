import os
import logging
from typing import List, Optional
from dotenv import load_dotenv

# Use python-dotenv to load .env and override any pre-set variables (e.g. from VS Code envFile)
load_dotenv(override=True)

# Telegram Bot Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
_allowed_users_str = os.getenv("ALLOWED_USERS", "")
ALLOWED_USERS_RAW = [user_id.strip().lower() for user_id in _allowed_users_str.split(",") if user_id.strip()]
ALLOWED_USERS = [int(user_id) for user_id in ALLOWED_USERS_RAW if user_id.isdigit()]

# AWS Configuration
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# DynamoDB Configuration
DYNAMODB_TABLE = os.getenv("DYNAMODB_TABLE", "BoxBotTable")
DYNAMODB_ENDPOINT = os.getenv("DYNAMODB_ENDPOINT")  # None in production

# App Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
MAX_ITEMS_PER_USER = int(os.getenv("MAX_ITEMS_PER_USER", "1000"))
MAX_STORAGE_LOCATIONS_PER_USER = int(os.getenv("MAX_STORAGE_LOCATIONS_PER_USER", "100"))

# Deployment Mode
DEPLOYMENT_MODE = os.getenv("DEPLOYMENT_MODE", "development")
IS_PRODUCTION = DEPLOYMENT_MODE.lower() == "production"

# Webhook Configuration
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# Configure logging
numeric_level = getattr(logging, LOG_LEVEL.upper(), None)
if not isinstance(numeric_level, int):
    numeric_level = logging.INFO

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=numeric_level
)

def is_user_allowed(user_id: int) -> bool:
    """Check if a user is allowed to use the bot."""
    if "all" in ALLOWED_USERS_RAW:
        return True
    return user_id in ALLOWED_USERS 
