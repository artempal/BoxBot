import json
import logging
import os

from telegram import Update
from telegram.ext import Dispatcher

from boxbot.bot.bot import create_application
from boxbot.config.config import TELEGRAM_TOKEN

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize bot application
updater = create_application()
dispatcher = updater.dispatcher

def lambda_handler(event, context):
    """AWS Lambda handler for BoxBot Telegram webhook."""
    logger.info('Event: %s', event)
    
    # Get request body
    if 'body' in event:
        try:
            body = json.loads(event['body'])
        except json.JSONDecodeError:
            logger.error("Failed to decode body as JSON")
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Invalid JSON in request body'})
            }
    else:
        logger.error("No body in event")
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'No body in request'})
        }
    
    # Process update
    try:
        update = Update.de_json(body, updater.bot)
        dispatcher.process_update(update)
        
        return {
            'statusCode': 200,
            'body': json.dumps({'status': 'ok'})
        }
    except Exception as e:
        logger.error("Error processing update: %s", str(e), exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        } 