import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode

from boxbot.db.dynamodb import DynamoDBManager
from boxbot.bot import states
from boxbot.bot.keyboards import (
    get_storage_locations_keyboard,
    get_storage_location_actions_keyboard,
    get_cancel_edit_keyboard,
    get_items_keyboard,
    safe_callback_data
)
from boxbot.config.config import is_user_allowed, MAX_STORAGE_LOCATIONS_PER_USER

logger = logging.getLogger(__name__)
db = DynamoDBManager()

def resolve_location_id_from_hash(location_id: str) -> str:
    """Восстанавливает полный ID локации из хеша, если необходимо"""
    if not location_id or len(location_id) > 10:
        return location_id
        
    try:
        # Попытка восстановить полный ID из хеша
        mapping_key = f"HASH_MAP#{location_id}"
        response = db.table.get_item(
            Key={
                'PK': 'SYSTEM',
                'SK': mapping_key
            }
        )
        
        item = response.get('Item')
        if item and 'orig_id' in item:
            original_id = item['orig_id']
            logger.info(f"Restored location ID from hash: {location_id} -> {original_id}")
            return original_id
    except Exception as e:
        logger.error(f"Error restoring location ID from hash: {e}")
        
    return location_id

# Storage location command handlers
async def handle_storage_command(update: Update, context) -> None:
    """Handle the /storage command."""
    user_id = update.effective_user.id
    
    if not is_user_allowed(user_id):
        await update.message.reply_text("⛔️ У вас нет доступа к этому боту.")
        return
    
    # Get all storage locations for this user
    result = db.list_storage_locations(user_id)
    locations = result['locations']
    
    # Get the user session and reset state
    session = db.get_user_session(user_id)
    session.state = states.IDLE
    session.context = {}
    db.save_user_session(session)
    
    if not locations:
        await update.message.reply_text(
            "У вас еще нет мест хранения. Нажмите кнопку «Добавить», чтобы создать новое место хранения.",
            reply_markup=get_storage_locations_keyboard(locations, user_id=user_id)
        )
    else:
        await update.message.reply_text(
            "Выберите место хранения:",
            reply_markup=get_storage_locations_keyboard(locations, user_id=user_id)
        )

async def handle_storage_callback(update: Update, context) -> None:
    """Handle callback queries for storage locations."""
    user_id = update.effective_user.id
    callback_data = update.callback_query.data
    
    # Log the callback data
    logger.info(f"Processing storage callback: {callback_data}")
    
    if not is_user_allowed(user_id):
        await update.callback_query.answer("⛔️ У вас нет доступа к этому боту.")
        return
    
    # Get the user session
    session = db.get_user_session(user_id)
    
    # Parse the callback data
    parts = callback_data.split(":")
    
    if len(parts) < 2:
        await update.callback_query.answer("Неверные данные обратного вызова.")
        return
    
    action = parts[1]
    
    # Handle different actions
    if action == "add":
        # Reset edit state if it was active
        if session.state == states.AWAITING_EDIT_STORAGE:
            session.state = states.IDLE
            session.context = {}
            db.save_user_session(session)
            
        # Start adding a new storage location
        session.state = states.AWAITING_STORAGE_NAME
        db.save_user_session(session)
        
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            "Отправьте название для нового места хранения:"
        )
    
    elif action == "view" and len(parts) >= 3:
        # Reset edit state if it was active for a different location
        if session.state == states.AWAITING_EDIT_STORAGE:
            current_location_id = session.context.get(states.STORAGE_ID)
            if current_location_id != parts[2]:  # If viewing a different location, reset edit mode
                session.state = states.IDLE
                session.context = {}
                db.save_user_session(session)
        
        # View a storage location
        location_id = parts[2]
        location_id = resolve_location_id_from_hash(location_id)
        location = db.get_storage_location(user_id, location_id)
        
        if not location:
            await update.callback_query.answer("Место хранения не найдено.")
            return
            
        # Format message
        message_text = f"📦 *{location.name}*\n\n"
        
        if location.items:
            message_text += "📋 *Содержимое:*\n"
            for item_name in location.items[:10]:  # Show first 10 items
                message_text += f"• {item_name}\n"
                
            if len(location.items) > 10:
                message_text += f"...и еще {len(location.items) - 10} вещей\n"
        else:
            message_text += "Это место хранения пусто.\n"
            
        message_text += "\n\n📸 Вы можете отправить фотографию, чтобы обновить фото места хранения"
        
        # Set state for potential photo uploads after viewing (but not for editing name without button)
        session.state = states.AWAITING_EDIT_STORAGE
        session.context = {
            states.STORAGE_ID: location_id,
            "allow_name_edit": False  # Flag to indicate name edit is not allowed without clicking Edit button
        }
        db.save_user_session(session)
        
        # Send photo if available, otherwise just text
        has_items = bool(location.items)
        keyboard = get_storage_location_actions_keyboard(location_id, has_items)
        if location.photo_id:
            await update.callback_query.message.reply_photo(
                photo=location.photo_id,
                caption=message_text,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.callback_query.message.reply_text(
                message_text,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
            
        await update.callback_query.answer()
    
    elif action == "page" and len(parts) >= 3:
        # Pagination for storage locations

        # Clear edit state if navigating away
        if session.state == states.AWAITING_EDIT_STORAGE:
            session.state = states.IDLE
            session.context = {} # Clear context which might hold storage_id
            logger.info(f"User {user_id} navigated away from edit mode.")
            # No need to save session yet, will be saved below

        try:
            page = int(parts[2])
            
            # Get all storage locations
            result = db.list_storage_locations(user_id)
            locations = result['locations']
            
            # Update message with new page
            await update.callback_query.message.edit_reply_markup(
                reply_markup=get_storage_locations_keyboard(locations, page, user_id=user_id)
            )
            
            # Update session context with page number and save
            session.context[states.LAST_STORAGE_PAGE] = page
            db.save_user_session(session) # Save session state and context
            
            await update.callback_query.answer()
        except ValueError:
            await update.callback_query.answer("Неверный номер страницы.")
            # Restore original state if something went wrong? Or just leave as IDLE? Leaving as IDLE for now.
            session.state = states.IDLE
            session.context = {}
            db.save_user_session(session)
    
    elif action == "edit" and len(parts) >= 3:
        # Start editing a storage location name/photo
        location_id = parts[2]
        location_id = resolve_location_id_from_hash(location_id)
        location = db.get_storage_location(user_id, location_id)
        
        if not location:
            await update.callback_query.answer("Место хранения не найдено.")
            return
            
        # Set state for editing with explicit flag allowing name editing
        session.state = states.AWAITING_EDIT_STORAGE
        session.context = {
            states.STORAGE_ID: location_id,
            "allow_name_edit": True  # Flag to indicate name edit is allowed
        }
        db.save_user_session(session)
        
        # TODO: Use a keyboard that includes a "Cancel Edit" button here
        await update.callback_query.answer()
        # Get the cancel keyboard
        cancel_keyboard = get_cancel_edit_keyboard(location_id)
        await update.callback_query.message.reply_text(
            f"Отправьте новое название для '{location.name}' или отправьте фотографию, чтобы обновить изображение.",
            reply_markup=cancel_keyboard
        )
        
    elif action == "cancel_edit" and len(parts) >= 3:
        # Cancel editing state
        location_id = parts[2]
        location_id = resolve_location_id_from_hash(location_id)
        original_location_id = session.context.get(states.STORAGE_ID)

        if session.state != states.AWAITING_EDIT_STORAGE or location_id != original_location_id:
            await update.callback_query.answer("Нечего отменять.")
            return

        # Reset state and clear context
        session.state = states.IDLE # Go back to idle state
        session.context = {}
        db.save_user_session(session)

        await update.callback_query.answer("Редактирование отменено.")
        # Maybe resend the 'view' message for this location_id?
        # For now, just inform the user. They can navigate back manually.
        await update.callback_query.message.edit_text(
             f"Редактирование места хранения отменено. Нажмите /storage для просмотра списка."
        )
        # TODO: Ideally, re-show the location view message instead of just text.
    
    elif action == "delete" and len(parts) >= 3:
        # Reset edit state if it was active
        if session.state == states.AWAITING_EDIT_STORAGE:
            session.state = states.IDLE
            session.context = {}
            db.save_user_session(session)
        
        # Delete a storage location
        location_id = parts[2]
        location_id = resolve_location_id_from_hash(location_id)
        location = db.get_storage_location(user_id, location_id)
        
        if not location:
            await update.callback_query.answer("Место хранения не найдено.")
            return
            
        if location.items:
            # If location has items, show option to move to trash
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(
                f"⚠️ Место хранения «{location.name}» содержит вещи.\n"
                f"Выберите действие:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🗑️ Удалить и переместить вещи в корзину", callback_data=f"storage:delete_with_items:{location_id}")],
                    [InlineKeyboardButton("❌ Отмена", callback_data=f"storage:view:{location_id}")]
                ])
            )
            return
            
        # Confirm deletion
        session.state = states.AWAITING_STORAGE_DELETE_CONFIRM
        session.context = {states.STORAGE_ID: location_id}
        db.save_user_session(session)
        
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            f"⚠️ Вы уверены, что хотите удалить место хранения «{location.name}»?\n"
            "Напишите название этого места хранения для подтверждения:"
        )
    
    elif action == "delete_with_items" and len(parts) >= 3:
        # Delete storage location with items
        location_id = parts[2]
        logger.info(f"Handling delete_with_items for location {location_id} and user {user_id}")
        
        location_id = resolve_location_id_from_hash(location_id)
        
        # Проверяем существование места хранения
        location = db.get_storage_location(user_id, location_id)
        
        if not location:
            logger.error(f"Location {location_id} not found for user {user_id} in delete_with_items")
            await update.callback_query.answer("Место хранения не найдено.")
            return
            
        # Проверяем наличие вещей
        if not location.items:
            logger.warning(f"Location {location_id} ({location.name}) has no items for user {user_id}")
            await update.callback_query.answer("Это место хранения пусто.")
            return
            
        logger.info(f"Setting state for confirmation with {len(location.items)} items")
        # Set state for confirmation
        session.state = states.AWAITING_STORAGE_DELETE_CONFIRM
        session.context = {
            states.STORAGE_ID: location_id,
            'move_to_trash': True
        }
        db.save_user_session(session)
        
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            f"⚠️ Вы уверены, что хотите удалить место хранения «{location.name}»?\n"
            f"Все вещи ({len(location.items)}) будут перемещены в корзину.\n"
            "Напишите название места хранения для подтверждения:"
        )
    
    elif action == "view_trash" and len(parts) >= 2:
        # View trash bin
        trash_bin = db.get_trash_bin(user_id)
        if not trash_bin:
            await update.callback_query.answer("Корзина не найдена.")
            return
            
        # Format message
        message_text = f"🗑️ *Корзина*\n\n"
        
        if trash_bin.items:
            message_text += "📋 *Содержимое:*\n"
            for item_name in trash_bin.items[:10]:
                message_text += f"• {item_name}\n"
                
            if len(trash_bin.items) > 10:
                message_text += f"...и еще {len(trash_bin.items) - 10} вещей\n"
                
        else:
            message_text += "Корзина пуста.\n"
            
        # Create keyboard with clear button if there are items
        keyboard = []
        if trash_bin.items:
            keyboard.append([InlineKeyboardButton("🗑️ Очистить корзину", callback_data=safe_callback_data("storage", "clear_trash"))])
            keyboard.append([InlineKeyboardButton("📋 Список вещей", callback_data=safe_callback_data("storage", "items", "trash_bin"))])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data=safe_callback_data("storage", "list"))])
        
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        
    elif action == "clear_trash" and len(parts) >= 2:
        # Clear trash bin
        trash_bin = db.get_trash_bin(user_id)
        if not trash_bin:
            await update.callback_query.answer("Корзина не найдена.")
            return
            
        if not trash_bin.items:
            await update.callback_query.answer("Корзина уже пуста.")
            return
            
        # Set state for confirmation
        session.state = states.AWAITING_TRASH_CLEAR_CONFIRM
        db.save_user_session(session)
        
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            f"⚠️ Вы уверены, что хотите очистить корзину?\n"
            f"Все вещи ({len(trash_bin.items)}) будут безвозвратно удалены.\n"
            "Напишите 'Очистить корзину' для подтверждения:"
        )
    
    elif action == "add_items" and len(parts) >= 3:
        # Reset edit state if it was active
        if session.state == states.AWAITING_EDIT_STORAGE:
            session.state = states.IDLE
            session.context = {}
            db.save_user_session(session)
        
        # Add items to a storage location
        location_id = parts[2]
        location_id = resolve_location_id_from_hash(location_id)
        location = db.get_storage_location(user_id, location_id)
        
        if not location:
            await update.callback_query.answer("Место хранения не найдено.")
            return
            
        # Set state for adding items
        session.state = states.AWAITING_ITEMS_LIST
        session.context = {states.STORAGE_ID: location_id}
        db.save_user_session(session)
        
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            f"Отправьте список вещей для добавления в «{location.name}».\n"
            "Каждая вещь должна быть на отдельной строке."
        )
    
    elif action == "items" and len(parts) >= 3:
        # Reset edit state if it was active
        if session.state == states.AWAITING_EDIT_STORAGE:
            session.state = states.IDLE
            session.context = {}
            db.save_user_session(session)
        
        # Show items in a storage location
        location_id = parts[2]
        location_id = resolve_location_id_from_hash(location_id)
        location = db.get_storage_location(user_id, location_id)
        
        if not location:
            await update.callback_query.answer("Место хранения не найдено.")
            return
            
        if not location.items:
            await update.callback_query.answer("Это место хранения пусто.")
            await update.callback_query.message.reply_text(
                f"📦 Место хранения «{location.name}» пусто.\n"
                "Используйте кнопку «Добавить вещи», чтобы добавить вещи."
            )
            return
            
        # Get items from this location
        items = []
        for item_name in location.items:
            item = db.get_item(user_id, item_name)
            if item:
                items.append(item)
                
        # Show items with pagination
        page = 0
        
        # Сохраняем контекст в сессию
        session.context['origin_context'] = {'origin': 'location', 'id': location_id, 'page': page}
        db.save_user_session(session)
        
        await update.callback_query.answer()
        # Try editing the existing message to show the items list
        try:
            reply_markup=get_items_keyboard(items, page, 10, location_id=location_id)
            logger.debug(f"Attempting to edit message with reply_markup: {reply_markup}") # Логирование
            # Check if the message has text content
            if hasattr(update.callback_query.message, 'text') and update.callback_query.message.text:
                await update.callback_query.message.edit_text(
                    f"📦 Вещи в «{location.name}»:",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                # If message doesn't have text (it's a photo or other media), send new message
                logger.debug(f"Original message has no text. Replying with new message.") # Логирование
                await update.callback_query.message.reply_text(
                    f"📦 Вещи в «{location.name}»:",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
        except Exception as e:
            logger.error(f"Error editing message for item list: {e}")
            # Fallback: send a new message if editing fails
            reply_markup=get_items_keyboard(items, page, 10, location_id=location_id)
            logger.debug(f"Fallback: Attempting to send new message with reply_markup: {reply_markup}") # Логирование
            await update.callback_query.message.reply_text(
                f"📦 Вещи в «{location.name}»:",
                reply_markup=reply_markup
            )
    
    elif action == "list":
        # Reset state regardless of what it was, including AWAITING_ITEMS_LIST
        session.state = states.IDLE
        session.context = {}
        db.save_user_session(session)
        
        # List all storage locations
        result = db.list_storage_locations(user_id)
        locations = result['locations']
        
        page = session.context.get(states.LAST_STORAGE_PAGE, 0)
        
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            "Выберите место хранения:",
            reply_markup=get_storage_locations_keyboard(locations, page, user_id=user_id)
        )

async def handle_new_storage_message(update: Update, context) -> None:
    """Handle messages when creating a new storage location."""
    user_id = update.effective_user.id
    
    if not is_user_allowed(user_id):
        await update.message.reply_text("⛔️ У вас нет доступа к этому боту.")
        return
    
    # Get user session
    session = db.get_user_session(user_id)
    
    if session.state == states.AWAITING_TRASH_CLEAR_CONFIRM:
        # User confirming trash bin clear
        confirmation_text = update.message.text.strip()
        if confirmation_text != "Очистить корзину":
            await update.message.reply_text(
                "❌ Подтверждение неверное. Удаление отменено."
            )
            session.state = states.IDLE
            db.save_user_session(session)
            return
            
        # Clear trash bin
        if db.clear_trash_bin(user_id):
            await update.message.reply_text("✅ Корзина очищена.")
        else:
            await update.message.reply_text("❌ Не удалось очистить корзину.")
            
        # Reset state
        session.state = states.IDLE
        db.save_user_session(session)
        
        # Show updated storage locations list
        result = db.list_storage_locations(user_id)
        locations = result['locations']
        await update.message.reply_text(
            "Выберите место хранения:",
            reply_markup=get_storage_locations_keyboard(locations, user_id=user_id)
        )
        return
        
    elif session.state == states.AWAITING_STORAGE_NAME:
        # Check storage location limit
        result = db.list_storage_locations(user_id)
        if len(result['locations']) >= MAX_STORAGE_LOCATIONS_PER_USER:
            await update.message.reply_text(
                f"⚠️ Достигнут лимит мест хранения ({MAX_STORAGE_LOCATIONS_PER_USER}).\n"
                "Удалите неиспользуемые места хранения, прежде чем добавлять новые."
            )
            session.state = states.IDLE
            db.save_user_session(session)
            return
            
        # User is sending a name for new storage location
        storage_name = update.message.text.strip()
        
        # Validate name
        if not storage_name:
            await update.message.reply_text("⚠️ Название места хранения не может быть пустым. Попробуйте еще раз:")
            return
            
        if len(storage_name) > 100:
            await update.message.reply_text("⚠️ Название слишком длинное (максимум 100 символов). Попробуйте еще раз:")
            return
            
        # Check for duplicate names
        existing_locations = db.search_storage_locations(user_id, storage_name)
        if any(loc.name.lower() == storage_name.lower() for loc in existing_locations):
            await update.message.reply_text(
                f"⚠️ Место хранения с названием «{storage_name}» уже существует.\n"
                "Используйте другое название:"
            )
            return
            
        # Create the storage location
        storage_location = db.create_storage_location(user_id, storage_name)
        
        # Set state for adding items
        session.state = states.AWAITING_ITEMS_LIST
        session.context = {states.STORAGE_ID: storage_location.id}
        db.save_user_session(session)
        
        # Create keyboard with back button
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        
        keyboard = [
            [InlineKeyboardButton("◀️ К местам хранения", callback_data="storage:list")]
        ]
        
        await update.message.reply_text(
            f"✅ Место хранения «{storage_name}» создано!\n\n"
            "Вы можете:\n"
            "• Отправить список вещей (каждая вещь на новой строке)\n"
            "• Отправить фотографию места хранения\n"
            "• Вернуться к местам хранения",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif session.state == states.AWAITING_EDIT_STORAGE:
        # User is editing a storage location name
        location_id = session.context.get(states.STORAGE_ID)
        if not location_id:
            session.state = states.IDLE
            db.save_user_session(session)
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте еще раз.")
            return
            
        location = db.get_storage_location(user_id, location_id)
        if not location:
            session.state = states.IDLE
            db.save_user_session(session)
            await update.message.reply_text("❌ Место хранения не найдено. Возможно, оно было удалено.")
            return
            
        # Check if name editing is allowed
        allow_name_edit = session.context.get("allow_name_edit", False)
        if not allow_name_edit:
            await update.message.reply_text("⚠️ Для изменения названия места хранения нажмите кнопку «Редактировать»")
            return
            
        # Update the name
        new_name = update.message.text.strip()
        
        # Validate name
        if not new_name:
            await update.message.reply_text("⚠️ Название места хранения не может быть пустым. Попробуйте еще раз:")
            return
            
        if len(new_name) > 100:
            await update.message.reply_text("⚠️ Название слишком длинное (максимум 100 символов). Попробуйте еще раз:")
            return
            
        # Check for duplicate names
        existing_locations = db.search_storage_locations(user_id, new_name)
        if any(loc.name.lower() == new_name.lower() and loc.id != location_id for loc in existing_locations):
            await update.message.reply_text(
                f"⚠️ Место хранения с названием «{new_name}» уже существует.\n"
                "Используйте другое название:"
            )
            return
            
        # Update the location
        old_name = location.name
        location.name = new_name
        db.update_storage_location(location)
        
        # Reset state
        session.state = states.IDLE
        db.save_user_session(session)
        
        # Show the updated location
        message_text = f"✅ Название изменено с «{old_name}» на «{new_name}»\n\n"
        
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
                reply_markup=get_storage_location_actions_keyboard(location_id, has_items),
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                message_text,
                reply_markup=get_storage_location_actions_keyboard(location_id, has_items),
                parse_mode=ParseMode.MARKDOWN
            )
    
    elif session.state == states.AWAITING_STORAGE_DELETE_CONFIRM:
        # User confirming storage location deletion
        location_id = session.context.get(states.STORAGE_ID)
        if not location_id:
            logger.error(f"Missing location_id in context for user {user_id} during delete confirmation")
            session.state = states.IDLE
            db.save_user_session(session)
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте еще раз.")
            return
            
        # Дополнительное логирование для отладки
        logger.info(f"Confirming deletion for location_id: {location_id}")
            
        location = db.get_storage_location(user_id, location_id)
        if not location:
            logger.error(f"Could not find location {location_id} for user {user_id} during delete confirmation")
            session.state = states.IDLE
            db.save_user_session(session)
            await update.message.reply_text("❌ Место хранения не найдено. Возможно, оно уже было удалено.")
            return
            
        # Check confirmation name
        confirmation_text = update.message.text.strip()
        if confirmation_text.lower() != location.name.lower():
            await update.message.reply_text(
                f"❌ Введенное название не соответствует «{location.name}».\n"
                "Удаление отменено."
            )
            session.state = states.IDLE
            db.save_user_session(session)
            return
            
        # Check if we need to move items to trash
        move_to_trash = session.context.get('move_to_trash', False)
        
        try:
            if move_to_trash and location.items:
                # Move items to trash
                logger.info(f"Moving {len(location.items)} items to trash for user {user_id}")
                db.move_items_to_trash(user_id, location.items)
                # Delete the location
                logger.info(f"Deleting location {location_id} for user {user_id}")
                db.delete_storage_location(user_id, location_id)
                await update.message.reply_text(
                    f"✅ Место хранения «{location.name}» удалено.\n"
                    f"Вещи ({len(location.items)}) перемещены в корзину."
                )
            else:
                # Delete the location
                logger.info(f"Deleting location {location_id} for user {user_id}")
                db.delete_storage_location(user_id, location_id)
                await update.message.reply_text(f"✅ Место хранения «{location.name}» удалено.")
        except Exception as e:
            logger.error(f"Error during location deletion: {e}")
            await update.message.reply_text("❌ Произошла ошибка при удалении места хранения.")
            
        # Reset state
        session.state = states.IDLE
        db.save_user_session(session)
        
        # Show updated storage locations list
        result = db.list_storage_locations(user_id)
        locations = result['locations']
        await update.message.reply_text(
            "Выберите место хранения:",
            reply_markup=get_storage_locations_keyboard(locations, user_id=user_id)
        )
    
    elif session.state == states.AWAITING_ITEMS_LIST:
        # User is sending list of items to add
        location_id = session.context.get(states.STORAGE_ID)
        if not location_id:
            session.state = states.IDLE
            db.save_user_session(session)
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте еще раз.")
            return
            
        location = db.get_storage_location(user_id, location_id)
        if not location:
            session.state = states.IDLE
            db.save_user_session(session)
            await update.message.reply_text("❌ Место хранения не найдено. Возможно, оно было удалено.")
            return
            
        # Parse items list (one item per line)
        items_text = update.message.text.strip()
        items_list = [item.strip() for item in items_text.split('\n') if item.strip()]
        
        if not items_list:
            await update.message.reply_text(
                "⚠️ Список вещей пуст. Отправьте хотя бы одну вещь, каждую на отдельной строке:"
            )
            return
            
        # Add items
        success_count = 0
        duplicate_items = []
        failed_items = []
        
        for item_name in items_list:
            try:
                db.create_item(user_id, item_name, location_id)
                success_count += 1
            except ValueError as e:
                if "already exists" in str(e):
                    duplicate_items.append(item_name)
                else:
                    failed_items.append(item_name)
        
        # Reset state
        session.state = states.IDLE
        db.save_user_session(session)
        
        # Prepare response message
        message = []
        if success_count > 0:
            message.append(f"✅ Успешно добавлено вещей: {success_count}")
            
        if duplicate_items:
            message.append(f"⚠️ Уже существующие вещи: {len(duplicate_items)}")
            if len(duplicate_items) <= 5:
                message.append("• " + "\n• ".join(duplicate_items))
                
        if failed_items:
            message.append(f"❌ Не удалось добавить: {len(failed_items)}")
            
        # Send response
        await update.message.reply_text("\n".join(message))
        
        # Show updated location
        location = db.get_storage_location(user_id, location_id)  # Refresh location data
        
        message_text = f"📦 *{location.name}*\n\n"
        
        if location.items:
            message_text += "📋 *Содержимое:*\n"
            for item_name in location.items[:10]:
                message_text += f"• {item_name}\n"
                
            if len(location.items) > 10:
                message_text += f"...и еще {len(location.items) - 10} вещей\n"
        
        has_items = bool(location.items)
        if location.photo_id:
            await update.message.reply_photo(
                photo=location.photo_id,
                caption=message_text,
                reply_markup=get_storage_location_actions_keyboard(location_id, has_items),
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                message_text,
                reply_markup=get_storage_location_actions_keyboard(location_id, has_items),
                parse_mode=ParseMode.MARKDOWN
            )

async def handle_skip_command(update: Update, context) -> None:
    """Handle the /skip command for skipping photo upload."""
    user_id = update.effective_user.id
    
    if not is_user_allowed(user_id):
        await update.message.reply_text("⛔️ У вас нет доступа к этому боту.")
        return
    
    # Get user session
    session = db.get_user_session(user_id)
    
    if session.state == states.AWAITING_STORAGE_PHOTO or session.state == states.AWAITING_ITEMS_LIST:
        # User is skipping photo upload for a new storage location
        location_id = session.context.get(states.STORAGE_ID)
        if not location_id:
            session.state = states.IDLE
            db.save_user_session(session)
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте еще раз с командой /storage")
            return
            
        location = db.get_storage_location(user_id, location_id)
        if not location:
            session.state = states.IDLE
            db.save_user_session(session)
            await update.message.reply_text("❌ Место хранения не найдено. Возможно, оно было удалено.")
            return
            
        # Reset state
        session.state = states.IDLE
        db.save_user_session(session)
        
        # Show the location
        message_text = f"📦 *{location.name}*\n\n"
        message_text += "Это место хранения пусто. Используйте кнопку «Добавить вещи», чтобы добавить вещи."
        
        await update.message.reply_text(
            message_text,
            reply_markup=get_storage_location_actions_keyboard(location_id, False),
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text("Команда /skip может использоваться только при создании места хранения.")

async def handle_photo_message(update: Update, context) -> None:
    """Handle photo messages for storage locations and items."""
    user_id = update.effective_user.id
    
    if not is_user_allowed(user_id):
        await update.message.reply_text("⛔️ У вас нет доступа к этому боту.")
        return
    
    # Get user session
    session = db.get_user_session(user_id)
    
    # Handle photo for a new storage location when awaiting either photo or items list
    if session.state == states.AWAITING_STORAGE_PHOTO or session.state == states.AWAITING_ITEMS_LIST:
        # User is sending a photo for a new storage location
        location_id = session.context.get(states.STORAGE_ID)
        if not location_id:
            session.state = states.IDLE
            db.save_user_session(session)
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте еще раз с командой /storage")
            return
            
        location = db.get_storage_location(user_id, location_id)
        if not location:
            session.state = states.IDLE
            db.save_user_session(session)
            await update.message.reply_text("❌ Место хранения не найдено. Возможно, оно было удалено.")
            return
            
        # Get the photo file_id
        photo_file_id = update.message.photo[-1].file_id
        
        # Update the location
        location.photo_id = photo_file_id
        db.update_storage_location(location)
        
        # Reset state
        session.state = states.IDLE
        db.save_user_session(session)
        
        # Show the location with photo
        message_text = f"📦 *{location.name}*\n\n"
        message_text += "Это место хранения пусто. Используйте кнопку «Добавить вещи», чтобы добавить вещи."
        
        await update.message.reply_photo(
            photo=photo_file_id,
            caption=message_text,
            reply_markup=get_storage_location_actions_keyboard(location_id, False),
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif session.state == states.AWAITING_EDIT_STORAGE:
        # User is updating the photo for an existing storage location
        location_id = session.context.get(states.STORAGE_ID)
        if not location_id:
            session.state = states.IDLE
            db.save_user_session(session)
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте еще раз.")
            return
            
        location = db.get_storage_location(user_id, location_id)
        if not location:
            session.state = states.IDLE
            db.save_user_session(session)
            await update.message.reply_text("❌ Место хранения не найдено. Возможно, оно было удалено.")
            return
            
        # Get the photo file_id
        photo_file_id = update.message.photo[-1].file_id
        
        # Update the location
        location.photo_id = photo_file_id
        db.update_storage_location(location)
        
        # Reset state
        session.state = states.IDLE
        db.save_user_session(session)
        
        # Show the updated location
        message_text = f"✅ Фотография для места хранения «{location.name}» обновлена!\n\n"
        
        if location.items:
            message_text += "📋 *Содержимое:*\n"
            for item_name in location.items[:10]:
                message_text += f"• {item_name}\n"
                
            if len(location.items) > 10:
                message_text += f"...и еще {len(location.items) - 10} вещей\n"
        else:
            message_text += "Это место хранения пусто.\n"
            
        has_items = bool(location.items)
        await update.message.reply_photo(
            photo=photo_file_id,
            caption=message_text,
            reply_markup=get_storage_location_actions_keyboard(location_id, has_items),
            parse_mode=ParseMode.MARKDOWN
        ) 