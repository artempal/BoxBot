import logging
from telegram import Update, InputMediaPhoto
from telegram.constants import ParseMode

from boxbot.db.dynamodb import DynamoDBManager
from boxbot.bot import states
from boxbot.bot.keyboards import (
    get_items_keyboard,
    get_item_actions_keyboard,
    get_move_item_keyboard
)
from boxbot.config.config import is_user_allowed, MAX_ITEMS_PER_USER
from boxbot.bot.i18n import t

logger = logging.getLogger(__name__)
db = DynamoDBManager()

# Item command handlers
async def handle_item_command(update: Update, context) -> None:
    """Handle the /item command."""
    user_id = update.effective_user.id
    
    if not is_user_allowed(user_id):
        # Access denied
        await update.message.reply_text(t('access_denied'))
        return
    
    # Get all items for this user
    result = db.list_items(user_id)
    items = result['items']
    page = 0 # Start on the first page
    
    # Get the user session and reset state/context
    session = db.get_user_session(user_id)
    session.state = states.IDLE
    # Сохраняем контекст основного списка в сессию
    session.context = {'origin_context': {'origin': 'main', 'page': page}}
    db.save_user_session(session)
    
    if not items:
        await update.message.reply_text(t('no_items'))
    else:
        await update.message.reply_text(
            t('item_select'),
            reply_markup=get_items_keyboard(items, page=page) # Pass page to keyboard
        )

async def handle_item_callback(update: Update, context) -> None:
    """Handle item-related callback queries."""
    query = update.callback_query
    user_id = update.effective_user.id
    callback_data = query.data
    
    # Log the callback data
    logger.info(f"Processing item callback: {callback_data}")
    
    # Get user session
    session = db.get_user_session(user_id)
    if not session:
        session = db.create_user_session(user_id)
        logger.warning(f"Created new session for user {user_id} during item callback.")
        # Если сессии не было, контекст будет пустым, обработка 'v' может быть неполной
        # Возможно, стоит запросить у пользователя повторить действие
    
    # Parse callback data
    parts = callback_data.split(":")
    action = parts[1] if len(parts) > 1 else None
    
    # Обрабатываем и старый и новый формат для list
    if action == "list":
        # List items (potentially within a location)
        location_id = parts[2] if len(parts) >= 3 else None
        items = []
        message_header = ""
        
        if location_id:
            # List items in a specific location
            location = db.get_storage_location(user_id, location_id)
            if location:
                item_names = location.items or []
                # Fetch full item objects, handling potential missing items
                items = [db.get_item(user_id, name) for name in item_names]
                items = [item for item in items if item] # Filter out None values if an item was deleted
                message_header = f"📦 Вещи в «{location.name}»:"
            else:
                await query.answer("Место хранения не найдено.")
                return
        else:
            # List all items (global list)
            result = db.list_items(user_id)
            items = result['items']
            message_header = t('item_list_header')
        
        if not items:
            no_items_text = t('no_items_in_location', location_name=location.name) if location_id and location else t('no_items')
            await query.answer()
            # Use edit_text if possible, otherwise reply
            try:
                await query.message.edit_text(no_items_text)
            except Exception:
                 await query.message.reply_text(no_items_text)
            return
            
        # Format items as a paginated list
        page = 0 # Always start at page 0 when returning to list
        items_per_page = 10
        
        await query.answer()
        # Edit the message to show the item list for the specific location or global list
        try:
            await query.message.edit_text(
                message_header,
                reply_markup=get_items_keyboard(items, page, items_per_page, location_id=location_id),
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
             logger.error(f"Error editing message for item list: {e}")
             # Fallback: send new message if edit fails (e.g., message too old)
             await query.message.reply_text(
                message_header,
                reply_markup=get_items_keyboard(items, page, items_per_page, location_id=location_id),
                parse_mode=ParseMode.MARKDOWN
            )
    
    # Поддержка новых сокращенных форматов пагинации
    elif action in ["page_loc", "pl"] and len(parts) >= 3:
        # Navigate pages for a specific location
        try:
            location_id = None
            page = 0
            if action == "page_loc": # Старый формат (на всякий случай)
                location_id = parts[2] if len(parts) >= 3 else None
                page = int(parts[3]) if len(parts) >= 4 else 0
            elif action == "pl": # Новый формат
                location_id = parts[2] if len(parts) >= 3 else None
                page = int(parts[3]) if len(parts) >= 4 else 0
                
            if not location_id:
                await query.answer("Неверный формат данных пагинации.")
                return
                
            location = db.get_storage_location(user_id, location_id)
            if not location or not location.items:
                await query.answer("Место хранения не найдено или пусто.")
                return
                
            items = []
            for item_name in location.items:
                item = db.get_item(user_id, item_name)
                if item:
                    items.append(item)
                    
            # Обновляем контекст сессии
            session.context['origin_context'] = {'origin': 'location', 'id': location_id, 'page': page}
            db.save_user_session(session)
                    
            # Update message with new page
            await query.answer()
            try:
                await query.message.edit_reply_markup(
                    reply_markup=get_items_keyboard(items, page, 10, location_id=location_id)
                )
            except Exception as e:
                logger.error(f"Error updating pagination: {e}")
                if "Message is not modified" not in str(e):
                     await query.answer("Не удалось обновить список.")
                
        except (ValueError, IndexError) as e:
            logger.error(f"Error parsing pagination callback {callback_data}: {e}")
            await query.answer("Ошибка пагинации.")
            
    # Поддержка новых сокращенных форматов пагинации для основного списка
    elif action in ["page_main", "pm"] and len(parts) >= 3:
        # Navigate pages for main items list
        try:
            page = int(parts[2])
            
            # Get all items
            result = db.list_items(user_id)
            items = result['items']
            
            # Обновляем контекст сессии
            session.context['origin_context'] = {'origin': 'main', 'page': page}
            db.save_user_session(session)
            
            # Update message with new page
            await query.answer()
            try:
                await query.message.edit_reply_markup(
                    reply_markup=get_items_keyboard(items, page, 10, location_id=None)
                )
            except Exception as e:
                logger.error(f"Error updating pagination: {e}")
                if "Message is not modified" not in str(e):
                     await query.answer("Не удалось обновить список.")
                
        except (ValueError, IndexError) as e:
            logger.error(f"Error parsing pagination callback {callback_data}: {e}")
            await query.answer("Ошибка пагинации.")
    
    # Поддержка нового сокращенного формата просмотра предмета
    elif action in ["view", "v"] and len(parts) >= 3:
        # View a specific item
        item_name = parts[2]
        # Обрабатываем случай, если имя предмета содержит ':'
        if len(parts) > 3:
            item_name = ":".join(parts[2:])
            
        item = db.get_item(user_id, item_name)

        if not item:
            # Localize item not found
            await query.answer(t('item_not_found'))
            return

        # Получаем контекст происхождения из сессии
        origin_context = session.context.get('origin_context')
        back_context = None
        if origin_context:
            if origin_context.get('origin') == 'location' and origin_context.get('id'):
                back_context = {"type": "location", "id": origin_context['id']}
            elif origin_context.get('origin') == 'main':
                back_context = {"type": "main", "page": origin_context.get('page', 0)}
        else:
             logger.warning(f"Missing origin_context in session for user {user_id} when viewing item {item_name}")
             # По умолчанию - возврат в основной список
             back_context = {"type": "main", "page": 0}

        # Get the storage location for display
        location = db.get_storage_location(user_id, item.storage_location_id)

        # Format the response
        message_text = f"📌 *{item_name}*\n\n"

        if location:
            message_text += f"📦 Место хранения: *{location.name}*\n"
        elif item.storage_location_id == 'trash_bin':
             message_text += f"🗑️ Находится в корзине\n"
        else:
            message_text += "⚠️ Место хранения не найдено (возможно, удалено)\n"

        if item.description:
            message_text += f"\n📝 Описание:\n{item.description}\n"

        message_text += "\n\n💡 Вы можете отправить фотографию, чтобы обновить фото вещи"

        # Set state to handle direct photo updates
        session.state = states.AWAITING_ITEM_PHOTO
        session.context[states.ITEM_NAME] = item_name
        db.save_user_session(session)

        await query.answer()

        try:
            current_message = query.message
            reply_markup = get_item_actions_keyboard(
                item_name=item_name,
                user_id=user_id,
                show_back_to_list_button=True,
                back_context=back_context # Используем контекст из сессии
            )
            
            logger.debug(f"Item view keyboard: {reply_markup}") # Логируем клавиатуру

            if item.photo_id:
                try:
                    # Проверяем, есть ли у текущего сообщения caption
                    if hasattr(current_message, 'caption') and current_message.caption is not None:
                        await current_message.edit_caption(
                             caption=message_text,
                             reply_markup=reply_markup,
                             parse_mode=ParseMode.MARKDOWN
                        )
                    else:
                        # Если caption нет (например, это было текстовое сообщение), отправляем новое фото
                        logger.info(f"Original message for item {item_name} had no caption. Sending new photo.")
                        await current_message.reply_photo(
                            photo=item.photo_id,
                            caption=message_text,
                            reply_markup=reply_markup,
                            parse_mode=ParseMode.MARKDOWN
                        )
                except Exception as e:
                    logger.warning(f"Failed to edit caption or reply with photo: {e}. Sending new photo message as fallback.")
                    # Дополнительный fallback: отправить новое фото сообщение
                    try:
                        await query.message.reply_photo(
                            photo=item.photo_id,
                            caption=message_text,
                            reply_markup=reply_markup,
                            parse_mode=ParseMode.MARKDOWN
                        )
                    except Exception as final_e:
                        logger.error(f"Final fallback failed for item view photo: {final_e}")
            else:
                # Если у предмета нет фото, редактируем текст или отправляем новый текст
                if hasattr(current_message, 'text') and current_message.text:
                    await current_message.edit_text(
                        message_text,
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    # Если сообщение не текстовое (например, было фото), отправляем новое текстовое сообщение
                    logger.info(f"Original message for item {item_name} was not text. Sending new text message.")
                    await current_message.reply_text(
                        message_text,
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.MARKDOWN
                    )
        except Exception as e:
            logger.error(f"Error sending/editing item view message: {e}")
            # Не отправляем пользователю ошибку Button_data_invalid, если она возникла здесь
            if not isinstance(e, telegram.error.BadRequest) or "Button_data_invalid" not in str(e):
                await query.message.reply_text(t('error_generic'))
    
    elif action == "edit" and len(parts) >= 3:
        # Edit an item
        item_name = parts[2]
        item = db.get_item(user_id, item_name)
        
        if not item:
            await query.answer("Вещь не найдена.")
            return
            
        # Get the edit type
        edit_type = parts[3] if len(parts) >= 4 else "menu"
        
        if edit_type == "menu":
            # Show edit menu
            await query.answer()
            
            message_text = f"✏️ *Редактирование вещи «{item_name}»*\n\n"
            message_text += "Выберите, что нужно изменить:"
            
            # Create an inline keyboard for edit options
            from telegram import InlineKeyboardMarkup, InlineKeyboardButton
            
            keyboard = [
                [InlineKeyboardButton("✏️ Название", callback_data=f"item:edit:{item_name}:name")],
                [InlineKeyboardButton("✏️ Описание", callback_data=f"item:edit:{item_name}:description")],
                [InlineKeyboardButton("🖼 Фотографию", callback_data=f"item:edit:{item_name}:photo")],
                [InlineKeyboardButton("🔙 Назад", callback_data=f"item:view:{item_name}")]
            ]
            
            await query.message.reply_text(
                message_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
            
        elif edit_type == "name":
            # Edit item name
            session.state = states.AWAITING_ITEM_EDIT
            session.context = {states.ITEM_NAME: item_name, states.EDIT_FIELD: "name"}
            db.save_user_session(session)
            
            await query.answer()
            await query.message.reply_text(
                f"✏️ Введите новое название для вещи «{item_name}»:"
            )
            
        elif edit_type == "description":
            # Edit description
            session.state = states.AWAITING_ITEM_EDIT
            session.context = {states.ITEM_NAME: item_name, states.EDIT_FIELD: "description"}
            db.save_user_session(session)
            
            current_desc = f"\n\nТекущее описание:\n{item.description}" if item.description else ""
            
            await query.answer()
            await query.message.reply_text(
                f"✏️ Введите новое описание для вещи «{item_name}»:{current_desc}"
            )
            
        elif edit_type == "photo":
            # Edit photo
            session.state = states.AWAITING_ITEM_EDIT
            session.context = {states.ITEM_NAME: item_name, states.EDIT_FIELD: "photo"}
            db.save_user_session(session)
            
            await query.answer()
            
            if item.photo_id:
                await query.message.reply_photo(
                    photo=item.photo_id,
                    caption=f"🖼 Текущая фотография вещи «{item_name}»\n\nОтправьте новую фотографию:"
                )
            else:
                await query.message.reply_text(
                    f"🖼 У вещи «{item_name}» пока нет фотографии.\n\nОтправьте фотографию:"
                )
    
    elif action == "delete" and len(parts) >= 3:
        # Delete an item
        item_name = parts[2]
        item = db.get_item(user_id, item_name)
        
        if not item:
            await query.answer("Вещь не найдена.")
            return
            
        # Move item to trash bin
        db.move_items_to_trash(user_id, [item_name])
        
        # Reset state
        session.state = states.IDLE
        db.save_user_session(session)
        
        await query.answer()
        await query.message.reply_text(
            f"✅ Вещь «{item_name}» перемещена в корзину."
        )
    
    elif action == "move" and len(parts) >= 3:
        # Move an item to a different location
        item_name = parts[2]
        item = db.get_item(user_id, item_name)

        if not item:
            await query.answer("Вещь не найдена.")
            return

        # Set session state for item move
        session.state = states.AWAITING_ITEM_MOVE
        session.context = {states.ITEM_NAME: item_name}
        db.save_user_session(session)

        # Get all storage locations
        result = db.list_storage_locations(user_id)
        locations = result['locations']

        if not locations:
            await query.answer("У вас нет мест хранения для перемещения.")
            await query.message.reply_text(
                "⚠️ У вас нет мест хранения. Создайте место хранения с помощью команды /storage"
            )
            return

        # Filter out the current location
        locations = [loc for loc in locations if loc.id != item.storage_location_id]

        if not locations:
            await query.answer("У вас нет других мест хранения для перемещения.")
            await query.message.reply_text(
                "⚠️ У вас нет других мест хранения для перемещения этой вещи.\n"
                "Создайте новое место хранения с помощью команды /storage"
            )
            return

        # Show locations for moving
        await query.answer()

        # Create keyboard manually to ensure valid callback data
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = []

        for location in locations:
            keyboard.append([
                InlineKeyboardButton(
                    location.name,
                    callback_data=f"item:move_to:{location.id}"
                )
            ])

        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data=f"item:view:{item_name}")])

        await query.message.reply_text(
            f"Выберите новое место хранения для «{item_name}»:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif action == "move_to" and len(parts) >= 3:
        # Complete item move to selected location
        new_location_id = parts[2]
        item_name = session.context.get(states.ITEM_NAME)
        if not item_name:
            await query.answer("Ошибка: отсутствует контекст перемещения.")
            return
        moved_item = db.move_item(user_id, item_name, new_location_id)
        if not moved_item:
            await query.answer("Вещь не найдена.")
            return
        # Reset session state
        session.state = states.IDLE
        session.context = {}
        db.save_user_session(session)
        await query.answer()
        await query.message.reply_text(
            f"✅ Вещь «{item_name}» успешно перемещена!", 
            reply_markup=get_item_actions_keyboard(
                item_name, 
                user_id, 
                location_id=new_location_id
            ), 
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif action == "move_page" and len(parts) >= 3:
        # Pagination for move item locations
        try:
            page = int(parts[2])
            item_name = session.context.get(states.ITEM_NAME)
            if not item_name:
                await query.answer("Ошибка: отсутствует контекст перемещения.")
                return

            # Get all storage locations except current
            item = db.get_item(user_id, item_name)
            if not item:
                await query.answer("Вещь не найдена.")
                return

            result = db.list_storage_locations(user_id)
            locations = [loc for loc in result['locations'] if loc.id != item.storage_location_id]

            # Update message with new page
            await query.answer()
            await query.message.edit_text(
                f"Выберите новое место хранения для «{item_name}»:",
                reply_markup=get_move_item_keyboard(item_name, locations, page),
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Ошибка при обновлении списка мест хранения: {e}")
            await query.answer("Не удалось обновить список.")
    
    elif action == "destroy" and len(parts) >= 3:
        # Permanently delete an item from trash bin
        item_name = parts[2]
        item = db.get_item(user_id, item_name)
        
        if not item:
            await query.answer("Вещь не найдена.")
            return
            
        if item.storage_location_id != 'trash_bin':
            await query.answer("Эта вещь не находится в корзине.")
            return
            
        # Delete the item permanently
        db.delete_item(user_id, item_name)
        
        # Reset state
        session.state = states.IDLE
        db.save_user_session(session)
        
        await query.answer()
        await query.message.reply_text(
            f"💥 Вещь «{item_name}» была безвозвратно удалена."
        )
    
    else:
        logger.warning(f"Unknown item action: {action} in callback {callback_data}")
        await query.answer("Неизвестное действие.")

async def handle_item_edit_message(update: Update, context) -> None:
    """Handle messages when editing an item."""
    user_id = update.effective_user.id
    
    if not is_user_allowed(user_id):
        await update.message.reply_text("⛔️ У вас нет доступа к этому боту.")
        return
    
    # Get user session
    session = db.get_user_session(user_id)
    
    if session.state == states.AWAITING_ITEM_EDIT:
        # User is editing an item name
        item_name = session.context.get(states.ITEM_NAME)
        if not item_name:
            session.state = states.IDLE
            db.save_user_session(session)
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте еще раз.")
            return
            
        item = db.get_item(user_id, item_name)
        if not item:
            session.state = states.IDLE
            db.save_user_session(session)
            await update.message.reply_text("❌ Вещь не найдена. Возможно, она была удалена.")
            return
            
        # Update the name
        new_name = update.message.text.strip()
        
        # Validate name
        if not new_name:
            await update.message.reply_text("⚠️ Название вещи не может быть пустым. Попробуйте еще раз:")
            return
            
        if len(new_name) > 100:
            await update.message.reply_text("⚠️ Название слишком длинное (максимум 100 символов). Попробуйте еще раз:")
            return
            
        # Check for duplicate names
        existing_items = db.search_items(user_id, new_name)
        for existing_item in existing_items:
            if existing_item.name.lower() == new_name.lower() and existing_item.name != item_name:
                await update.message.reply_text(
                    f"⚠️ Вещь с названием «{new_name}» уже существует. Выберите другое название:"
                )
                return
                
        # Update field based on what's being edited
        edit_field = session.context.get(states.EDIT_FIELD)
        
        if edit_field == "name":
            # Update name
            old_name = item.name
            item.name = new_name
            db.update_item(item)
            
            # Reset state
            session.state = states.IDLE
            db.save_user_session(session)
            
            # Get the storage location
            location = db.get_storage_location(user_id, item.storage_location_id)
            
            # Show the updated item
            message_text = f"✅ Название изменено с «{old_name}» на «{new_name}»\n\n"
            
            if location:
                message_text += f"📦 Место хранения: *{location.name}*\n"
            else:
                message_text += "⚠️ Место хранения не найдено (возможно, удалено)\n"
                
            if item.description:
                message_text += f"\n📝 {item.description}\n"
            
            # If the item has a photo, send it with the caption
            if item.photo_id:
                await update.message.reply_photo(
                    photo=item.photo_id,
                    caption=message_text,
                    reply_markup=get_item_actions_keyboard(
                        new_name, 
                        user_id, 
                        location_id=item.storage_location_id
                    ),
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    message_text,
                    reply_markup=get_item_actions_keyboard(
                        new_name, 
                        user_id, 
                        location_id=item.storage_location_id
                    ),
                    parse_mode=ParseMode.MARKDOWN
                )
                
        elif edit_field == "description":
            # Update description
            item.description = new_name  # Using new_name as the description content
            db.update_item(item)
            
            # Reset state
            session.state = states.IDLE
            db.save_user_session(session)
            
            # Get the storage location
            location = db.get_storage_location(user_id, item.storage_location_id)
            
            # Show the updated item
            message_text = f"✅ Описание для вещи «{item_name}» обновлено!\n\n"
            
            if location:
                message_text += f"📦 Место хранения: *{location.name}*\n"
            else:
                message_text += "⚠️ Место хранения не найдено (возможно, удалено)\n"
                
            message_text += f"\n📝 {item.description}\n"
            
            # If the item has a photo, send it with the caption
            if item.photo_id:
                await update.message.reply_photo(
                    photo=item.photo_id,
                    caption=message_text,
                    reply_markup=get_item_actions_keyboard(
                        item_name, 
                        user_id, 
                        location_id=item.storage_location_id
                    ),
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    message_text,
                    reply_markup=get_item_actions_keyboard(
                        item_name, 
                        user_id, 
                        location_id=item.storage_location_id
                    ),
                    parse_mode=ParseMode.MARKDOWN
                )
    
    elif session.state == states.AWAITING_ITEM_DELETE_CONFIRM:
        # User confirming item deletion
        item_name = session.context.get(states.ITEM_NAME)
        if not item_name:
            session.state = states.IDLE
            db.save_user_session(session)
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте еще раз.")
            return
            
        item = db.get_item(user_id, item_name)
        if not item:
            session.state = states.IDLE
            db.save_user_session(session)
            await update.message.reply_text("❌ Вещь не найдена. Возможно, она уже была удалена.")
            return
            
        # Check confirmation name
        confirmation_text = update.message.text.strip()
        if confirmation_text.lower() != item_name.lower():
            await update.message.reply_text(
                f"❌ Введенное название не соответствует «{item_name}».\n"
                "Удаление отменено."
            )
            session.state = states.IDLE
            db.save_user_session(session)
            return
        
        # Delete the item
        db.delete_item(user_id, item_name)
        
        # Reset state
        session.state = states.IDLE
        db.save_user_session(session)
        
        await update.message.reply_text(f"✅ Вещь «{item_name}» была удалена.")

async def handle_item_photo_message(update: Update, context) -> None:
    """Handle photo messages for items."""
    user_id = update.effective_user.id
    
    if not is_user_allowed(user_id):
        await update.message.reply_text("⛔️ У вас нет доступа к этому боту.")
        return
    
    # Get user session
    session = db.get_user_session(user_id)
    
    if session.state in [states.AWAITING_ITEM_EDIT, states.AWAITING_ITEM_PHOTO]:
        # User is updating the photo for an item
        item_name = session.context.get(states.ITEM_NAME)
        if not item_name:
            session.state = states.IDLE
            db.save_user_session(session)
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте еще раз.")
            return
            
        item = db.get_item(user_id, item_name)
        if not item:
            session.state = states.IDLE
            db.save_user_session(session)
            await update.message.reply_text("❌ Вещь не найдена. Возможно, она была удалена.")
            return
            
        # Get the photo file_id
        photo_file_id = update.message.photo[-1].file_id
        
        # Update the item
        item.photo_id = photo_file_id
        db.update_item(item)
        
        # Reset state
        session.state = states.IDLE
        db.save_user_session(session)
        
        # Get the storage location
        location = db.get_storage_location(user_id, item.storage_location_id)
        
        # Show the updated item
        message_text = f"✅ Фотография для вещи «{item_name}» обновлена!\n\n"
        
        if location:
            message_text += f"📦 Место хранения: *{location.name}*\n"
        else:
            message_text += "⚠️ Место хранения не найдено (возможно, удалено)\n"
            
        if item.description:
            message_text += f"\n📝 Описание:\n{item.description}\n"
            
    
        await update.message.reply_photo(
            photo=photo_file_id,
            caption=message_text,
            reply_markup=get_item_actions_keyboard(
                item_name, 
                user_id, 
                location_id=item.storage_location_id
            ),
            parse_mode=ParseMode.MARKDOWN
        ) 