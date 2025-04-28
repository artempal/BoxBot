import logging
import os
import sys
import requests
import json

from boxbot.config.config import TELEGRAM_TOKEN, WEBHOOK_URL

logger = logging.getLogger()
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
logger.addHandler(handler)

def setup_webhook():
    """Set up the webhook for the Telegram bot."""
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN is not set")
        sys.exit(1)
        
    if not WEBHOOK_URL:
        logger.error("WEBHOOK_URL is not set")
        sys.exit(1)
    
    # Set the webhook URL
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"
    payload = {
        "url": WEBHOOK_URL,
        "max_connections": 40,
        "drop_pending_updates": True,
    }
    
    response = requests.post(url, json=payload)
    
    if response.status_code == 200 and response.json().get("ok"):
        logger.info("Webhook set successfully!")
        logger.info(f"Webhook URL: {WEBHOOK_URL}")
        
        # Get webhook info
        info_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getWebhookInfo"
        info_response = requests.get(info_url)
        
        if info_response.status_code == 200:
            logger.info("Webhook info:")
            logger.info(json.dumps(info_response.json(), indent=2))
        else:
            logger.error(f"Failed to get webhook info: {info_response.text}")
    else:
        logger.error(f"Failed to set webhook: {response.text}")
        sys.exit(1)

if __name__ == "__main__":
    setup_webhook() 