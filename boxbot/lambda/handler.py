import json
import logging
import os
import asyncio

from telegram import Update

from boxbot.bot.bot import create_application
from boxbot.config.config import TELEGRAM_TOKEN

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize bot application
application = create_application()

async def initialize_and_process_update(update):
    """Initialize the application and process the update."""
    # Initialize the application before processing the update
    await application.initialize()
    await application.process_update(update)
    # Shutdown to clean up resources
    await application.shutdown()

def handler(event, context):
    """
    Yandex Cloud Functions handler for BoxBot Telegram webhook.
    
    Yandex Cloud Functions passes the HTTP request in the 'event' parameter
    with a different structure than AWS Lambda.
    """
    logger.info('Event: %s', event)
    
    # Get request body from Yandex Cloud Functions event structure
    try:
        # Yandex Cloud Functions provides the body directly in the 'body' field
        if isinstance(event, dict) and 'body' in event:
            try:
                body = json.loads(event['body'])
            except json.JSONDecodeError:
                logger.error("Failed to decode body as JSON")
                return {
                    'statusCode': 400,
                    'body': json.dumps({'error': 'Invalid JSON in request body'})
                }
        else:
            logger.error("No body in event or unexpected event format")
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'No body in request or invalid format'})
            }
        
        # Process update
        update = Update.de_json(body, application.bot)
        
        # Initialize the application and process the update
        asyncio.run(initialize_and_process_update(update))
        
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
