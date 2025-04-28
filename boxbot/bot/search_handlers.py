import logging
import Levenshtein
from typing import List, Dict, Tuple
from telegram import Update, InputMediaPhoto
from telegram.constants import ParseMode

from boxbot.db.dynamodb import DynamoDBManager
from boxbot.db.models import StorageLocation, Item
from boxbot.bot import states
from boxbot.bot.keyboards import (
    get_storage_locations_keyboard,
    get_items_keyboard,
    get_item_actions_keyboard,
    get_storage_location_actions_keyboard
)
from boxbot.config.config import is_user_allowed

logger = logging.getLogger(__name__)
db = DynamoDBManager()

# Fuzzy search threshold (0-1, higher is more strict)
FUZZY_THRESHOLD = 0.7

async def handle_search(update: Update, context) -> None:
    """Handle text messages as search queries."""
    user_id = update.effective_user.id
    
    if not is_user_allowed(user_id):
        await update.message.reply_text("⛔️ У вас нет доступа к этому боту.")
        return
    
    # Get user session
    session = db.get_user_session(user_id)
    
    # Reset search context for fresh query if a previous search was in progress
    if session.state == states.SEARCHING:
        session.state = states.IDLE
        session.context = {}
        db.save_user_session(session)
    
    # Check if we're in a special state
    if session.state in [
        states.AWAITING_STORAGE_NAME, 
        states.AWAITING_EDIT_STORAGE,
        states.AWAITING_ITEMS_LIST,
        states.AWAITING_ITEM_EDIT,
        states.AWAITING_ITEM_DELETE_CONFIRM,
        states.AWAITING_STORAGE_DELETE_CONFIRM
    ]:
        # Let other handlers process this message
        return
    
    # Search query
    query = update.message.text.strip().lower()
    
    if not query:
        return
    
    # Determine search type from context if in SEARCHING state
    search_type = states.SEARCH_BOTH
    if session.state == states.SEARCHING:
        search_type = session.context.get(states.SEARCH_TYPE, states.SEARCH_BOTH)
    
    # Perform search
    if search_type in [states.SEARCH_STORAGE, states.SEARCH_BOTH]:
        # Search storage locations
        storage_locations = db.search_storage_locations(user_id, query)
        
        # Add fuzzy matching if exact match not found
        if not storage_locations:
            all_locations = db.list_storage_locations(user_id)['locations']
            storage_locations = fuzzy_search_locations(query, all_locations)
    else:
        storage_locations = []
    
    if search_type in [states.SEARCH_ITEM, states.SEARCH_BOTH]:
        # Search items
        items = db.search_items(user_id, query)
        
        # Add fuzzy matching if exact match not found
        if not items:
            all_items = db.list_items(user_id)['items']
            items = fuzzy_search_items(query, all_items)
    else:
        items = []
    
    # Handle results
    if len(storage_locations) == 1 and not items:
        # Single storage location found
        location = storage_locations[0]
        
        # View the location directly
        message_text = f"📦 *{location.name}*\n\n"
        
        if location.items:
            message_text += "📋 *Содержимое:*\n"
            for item_name in location.items[:10]:
                message_text += f"• {item_name}\n"
                
            if len(location.items) > 10:
                message_text += f"...и еще {len(location.items) - 10} вещей\n"
        else:
            message_text += "Это место хранения пусто.\n"
        
        has_items = bool(location.items)
        if location.photo_id:
            await update.message.reply_photo(
                photo=location.photo_id,
                caption=message_text,
                reply_markup=get_storage_location_actions_keyboard(location.id, has_items),
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                message_text,
                reply_markup=get_storage_location_actions_keyboard(location.id, has_items),
                parse_mode=ParseMode.MARKDOWN
            )
    
    elif not storage_locations and len(items) == 1:
        # Single item found
        item = items[0]
        
        # Increment usage count for statistics
        db.increment_usage_count(user_id, item.name)
        
        # Get the storage location
        location = db.get_storage_location(user_id, item.storage_location_id)
        
        # Format message
        message_text = f"📌 *{item.name}*\n\n"
        
        if location:
            message_text += f"📦 Место хранения: *{location.name}*\n"
        else:
            message_text += "⚠️ Место хранения не найдено (возможно, удалено)\n"
            
        if item.description:
            message_text += f"\n📝 Описание:\n{item.description}\n"
            
        message_text += f"\n🔢 Количество обращений: {item.usage_count}"
        message_text += "\n\n💡 Вы можете отправить фотографию, чтобы обновить фото вещи"
        
        # Set state to handle direct photo updates
        session.state = states.AWAITING_ITEM_PHOTO
        session.context[states.ITEM_NAME] = item.name
        db.save_user_session(session)
        
        # Send storage location photo if available
        if location and location.photo_id:
            await update.message.reply_photo(
                photo=location.photo_id,
                caption=f"📦 Место хранения: *{location.name}*",
                parse_mode=ParseMode.MARKDOWN
            )
        
        # Send item photo if available
        if item.photo_id:
            await update.message.reply_photo(
                photo=item.photo_id,
                caption=message_text,
                reply_markup=get_item_actions_keyboard(item.name, user_id, show_back_to_list_button=False),
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            # If no photos, send just the text message
            await update.message.reply_text(
                message_text,
                reply_markup=get_item_actions_keyboard(item.name, user_id, show_back_to_list_button=False),
                parse_mode=ParseMode.MARKDOWN
            )
    
    elif storage_locations and not items:
        # Multiple storage locations found
        await update.message.reply_text(
            f"Найдено мест хранения: {len(storage_locations)}",
            reply_markup=get_storage_locations_keyboard(storage_locations)
        )
        
        # Set search state
        session.state = states.SEARCHING
        session.context = {states.SEARCH_TYPE: states.SEARCH_STORAGE}
        db.save_user_session(session)
    
    elif not storage_locations and items:
        # Multiple items found
        await update.message.reply_text(
            f"Найдено вещей: {len(items)}",
            reply_markup=get_items_keyboard(items)
        )
        
        # Set search state
        session.state = states.SEARCHING
        session.context = {states.SEARCH_TYPE: states.SEARCH_ITEM}
        db.save_user_session(session)
    
    elif storage_locations and items:
        # Both storage locations and items found
        total_results = len(storage_locations) + len(items)
        
        message = f"Найдено результатов: {total_results}\n\n"
        message += f"📦 Места хранения ({len(storage_locations)}):\n"
        
        for loc in storage_locations[:5]:
            message += f"• {loc.name}\n"
            
        if len(storage_locations) > 5:
            message += "...\n"
            
        message += f"\n📝 Вещи ({len(items)}):\n"
        
        for item in items[:5]:
            message += f"• {item.name}\n"
            
        if len(items) > 5:
            message += "...\n"
            
        message += "\nВыберите, что именно вы ищете:"
        
        # Custom keyboard for combined results
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        
        keyboard = [
            [InlineKeyboardButton(f"📦 Места хранения ({len(storage_locations)})", callback_data="search:locations")],
            [InlineKeyboardButton(f"📝 Вещи ({len(items)})", callback_data="search:items")]
        ]
        
        # Store results in session
        session.state = states.SEARCHING
        session.context = {
            states.SEARCH_TYPE: states.SEARCH_BOTH,
            "storage_locations": [loc.id for loc in storage_locations],
            "items": [item.name for item in items]
        }
        db.save_user_session(session)
        
        await update.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    else:
        # No results found
        await update.message.reply_text(
            "🔍 Ничего не найдено по вашему запросу.\n"
            "Попробуйте другой поисковый запрос или используйте команды /storage и /item."
        )

async def handle_search_callback(update: Update, context) -> None:
    """Handle search-related callbacks."""
    user_id = update.effective_user.id
    callback_data = update.callback_query.data
    
    if not is_user_allowed(user_id):
        await update.callback_query.answer("⛔️ У вас нет доступа к этому боту.")
        return
    
    # Get the user session
    session = db.get_user_session(user_id)
    
    # Check if we're in the SEARCHING state
    if session.state != states.SEARCHING:
        await update.callback_query.answer("Поиск не активен.")
        return
    
    # Parse the callback data
    parts = callback_data.split(":")
    
    if len(parts) < 2:
        await update.callback_query.answer("Неверные данные обратного вызова.")
        return
    
    action = parts[1]
    
    if action == "locations":
        # Show storage locations from search results
        location_ids = session.context.get("storage_locations", [])
        locations = []
        
        for loc_id in location_ids:
            location = db.get_storage_location(user_id, loc_id)
            if location:
                locations.append(location)
        
        if not locations:
            await update.callback_query.answer("Места хранения не найдены.")
            return
            
        await update.callback_query.answer()
        await update.callback_query.message.edit_text(
            "Найденные места хранения:",
            reply_markup=get_storage_locations_keyboard(locations)
        )
    
    elif action == "items":
        # Show items from search results
        item_names = session.context.get("items", [])
        items = []
        
        for item_name in item_names:
            item = db.get_item(user_id, item_name)
            if item:
                items.append(item)
        
        if not items:
            await update.callback_query.answer("Вещи не найдены.")
            return
            
        await update.callback_query.answer()
        await update.callback_query.message.edit_text(
            "Найденные вещи:",
            reply_markup=get_items_keyboard(items)
        )
    
    elif action == "view" and len(parts) >= 3:
        # View a specific item from search results
        item_name = parts[2]
        item = db.get_item(user_id, item_name)
        
        if not item:
            await update.callback_query.answer("Вещь не найдена.")
            return
            
        # Increment usage count for statistics
        db.increment_usage_count(user_id, item.name)
        
        # Get the storage location
        location = db.get_storage_location(user_id, item.storage_location_id)
        
        # Format message
        message_text = f"📌 *{item.name}*\n\n"
        
        if location:
            message_text += f"📦 Место хранения: *{location.name}*\n"
        else:
            message_text += "⚠️ Место хранения не найдено (возможно, удалено)\n"
            
        if item.description:
            message_text += f"\n📝 Описание:\n{item.description}\n"
            
        message_text += f"\n🔢 Количество обращений: {item.usage_count}"
        
        # Set state to handle direct photo updates
        session.state = states.AWAITING_ITEM_PHOTO
        session.context[states.ITEM_NAME] = item_name
        db.save_user_session(session)
        
        # Create media group for photos
        media_group = []
        
        # Add storage location photo if available
        if location and location.photo_id:
            media_group.append(
                InputMediaPhoto(
                    media=location.photo_id,
                    caption=f"📦 Место хранения: *{location.name}*",
                    parse_mode=ParseMode.MARKDOWN
                )
            )
        
        # Add item photo if available
        if item.photo_id:
            media_group.append(
                InputMediaPhoto(
                    media=item.photo_id,
                    caption=message_text,
                    parse_mode=ParseMode.MARKDOWN
                )
            )
        
        # Send the media group
        await update.callback_query.message.reply_media_group(media_group)
        
        # Send the keyboard separately
        await update.callback_query.message.reply_text(
            "Выберите действие:",
            reply_markup=get_item_actions_keyboard(item.name, user_id, show_back_to_list_button=False)
        )

def fuzzy_search_locations(query: str, locations: List[StorageLocation]) -> List[StorageLocation]:
    """Perform fuzzy search on storage locations."""
    results = []
    
    for location in locations:
        # Calculate similarity ratio
        ratio = Levenshtein.ratio(query.lower(), location.name.lower())
        
        if ratio >= FUZZY_THRESHOLD:
            results.append(location)
    
    # Sort by similarity (most similar first)
    results.sort(key=lambda x: Levenshtein.ratio(query.lower(), x.name.lower()), reverse=True)
    
    return results

def fuzzy_search_items(query: str, items: List[Item]) -> List[Item]:
    """Perform fuzzy search on items."""
    results = []
    
    for item in items:
        # Calculate similarity ratio
        ratio = Levenshtein.ratio(query.lower(), item.name.lower())
        
        if ratio >= FUZZY_THRESHOLD:
            results.append(item)
    
    # Sort by similarity (most similar first)
    results.sort(key=lambda x: Levenshtein.ratio(query.lower(), x.name.lower()), reverse=True)
    
    return results 