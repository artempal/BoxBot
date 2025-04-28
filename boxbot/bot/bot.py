import logging
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    Defaults,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters
)

from boxbot.config.config import TELEGRAM_TOKEN, IS_PRODUCTION, WEBHOOK_URL, is_user_allowed
from boxbot.db.dynamodb import DynamoDBManager
from boxbot.bot.storage_handlers import (
    handle_storage_command,
    handle_storage_callback,
    handle_new_storage_message,
    handle_skip_command,
    handle_photo_message
)
from boxbot.bot.item_handlers import (
    handle_item_command,
    handle_item_callback,
    handle_item_edit_message,
    handle_item_photo_message
)
from boxbot.bot.search_handlers import (
    handle_search,
    handle_search_callback
)
from boxbot.bot.i18n import t
from boxbot.bot import states

logger = logging.getLogger(__name__)
db = DynamoDBManager()


async def start(update: Update, context) -> None:
    """Send a message when the command /start is issued."""
    user_id = update.effective_user.id
    name = update.effective_user.first_name
    
    # Initialize user session
    session = db.get_user_session(user_id)
    session.state = states.IDLE
    session.context = {}
    db.save_user_session(session)
    
    # Get greeting text
    text = t('start', name=name)
    await update.effective_message.reply_text(text, parse_mode='Markdown')


async def help_command(update: Update, context) -> None:
    """Send a message when the command /help is issued."""
    text = t('help')
    await update.effective_message.reply_text(text, parse_mode='Markdown')


async def stat_command(update: Update, context) -> None:
    """Handle the /stat command."""
    user_id = update.effective_user.id
    
    if not is_user_allowed(user_id):
        await update.message.reply_text(t('access_denied'))
        return

    # Get top items and locations
    top_items = db.get_top_items(user_id)
    top_locations = db.get_top_locations(user_id)

    # Build statistics message
    message = f"{t('stats_header')}\n\n"

    # Top items
    message += f"{t('stats_top_items')}\n"
    if top_items:
        for i, item in enumerate(top_items, 1):
            message += f"{i}. {item.name} - {item.usage_count} {t('hits')}\n"
    else:
        message += f"{t('no_data')}\n"

    message += "\n"

    # Top locations
    message += f"{t('stats_top_locations')}\n"
    if top_locations:
        for i, location in enumerate(top_locations, 1):
            message += f"{i}. {location.name} - {location.usage_count} {t('hits')}\n"
    else:
        message += f"{t('no_data')}\n"

    await update.message.reply_text(message, parse_mode='Markdown')


async def set_commands(application) -> None:
    """Set bot commands in the menu."""
    commands = [
        BotCommand("storage", "Управление местами хранения"),
        BotCommand("item", "Просмотр списка вещей"),
        BotCommand("stat", "Статистика поиска"),
        BotCommand("help", "Справка и помощь"),
    ]
    await application.bot.set_my_commands(commands)


async def message_router(update: Update, context) -> None:
    """Route messages to appropriate handlers based on state."""
    if not update.message or not update.message.text:
        return
        
    user_id = update.effective_user.id
    session = db.get_user_session(user_id)
    
    if session.state in [
        states.AWAITING_STORAGE_NAME,
        states.AWAITING_EDIT_STORAGE,
        states.AWAITING_ITEMS_LIST,
        states.AWAITING_STORAGE_DELETE_CONFIRM,
        states.AWAITING_TRASH_CLEAR_CONFIRM
    ]:
        # Handle storage-related messages
        await handle_new_storage_message(update, context)
    elif session.state in [
        states.AWAITING_ITEM_EDIT,
        states.AWAITING_ITEM_DELETE_CONFIRM
    ]:
        # Handle item-related messages
        await handle_item_edit_message(update, context)
    else:
        # Handle search queries for items and locations
        await handle_search(update, context)


async def photo_router(update: Update, context) -> None:
    """Route photo messages to appropriate handlers based on state."""
    if not update.message or not update.message.photo:
        return
        
    user_id = update.effective_user.id
    session = db.get_user_session(user_id)
    
    if session.state in [
        states.AWAITING_STORAGE_PHOTO,
        states.AWAITING_ITEMS_LIST,
        states.AWAITING_EDIT_STORAGE
    ]:
        # Handle storage-related photos
        await handle_photo_message(update, context)
    elif session.state in [states.AWAITING_ITEM_EDIT, states.AWAITING_ITEM_PHOTO]:
        # Handle item-related photos
        await handle_item_photo_message(update, context)


async def callback_router(update: Update, context) -> None:
    """Route callback queries to appropriate handlers."""
    if not update.callback_query or not update.callback_query.data:
        return
        
    callback_data = update.callback_query.data
    
    if callback_data.startswith("storage:"):
        # Handle storage-related callbacks
        await handle_storage_callback(update, context)
    elif callback_data.startswith("item:"):
        # Handle item-related callbacks
        await handle_item_callback(update, context)
    elif callback_data.startswith("search:"):
        # Handle search-related callbacks
        await handle_search_callback(update, context)
    elif callback_data == "start":
        # Return to start
        await update.callback_query.answer()
        await start(update, context)


def create_application():
    """Create and configure the telegram bot application."""
    # Create the Application with bot token
    import pytz
    application = Application.builder().token(TELEGRAM_TOKEN).defaults(Defaults(tzinfo=pytz.UTC)).build()
    # Create DynamoDB table if it doesn't exist
    db.create_table_if_not_exists()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("storage", handle_storage_command))
    application.add_handler(CommandHandler("item", handle_item_command))
    application.add_handler(CommandHandler("stat", stat_command))
    application.add_handler(CommandHandler("skip", handle_skip_command))
    
    # Add callback query handler
    application.add_handler(CallbackQueryHandler(callback_router))
    
    # Add message handlers
    application.add_handler(MessageHandler(filters.PHOTO, photo_router))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))

    # Set up post_init function
    async def post_init_hook(app):
        await set_commands(app)
        
    application.post_init = post_init_hook

    return application


def run_polling():
    """Run the bot with polling (development mode)."""
    logger.info("Starting bot in polling mode (development)")
    application = create_application()
    # Start polling synchronously
    application.run_polling()


def run_webhook():
    """Run the bot with webhook (production mode)."""
    logger.info("Starting bot in webhook mode (production)")
    application = create_application()
    # Start webhook synchronously
    application.run_webhook(
        listen="0.0.0.0",
        port=8000,
        url_path=TELEGRAM_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_TOKEN}"
    )


def main():
    """Main function to run the bot."""
    # Initialize logging
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO
    )
    # Run in appropriate mode synchronously
    if IS_PRODUCTION:
        run_webhook()
    else:
        run_polling()


if __name__ == "__main__":
    main() 