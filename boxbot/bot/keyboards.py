import logging
from typing import List, Dict, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import hashlib
from datetime import datetime

from boxbot.db.models import StorageLocation, Item
from boxbot.bot.i18n import t
from boxbot.db.dynamodb import DynamoDBManager

logger = logging.getLogger(__name__)
db = DynamoDBManager()

# Максимальная длина callback_data в Telegram
MAX_CALLBACK_LENGTH = 60  # Оставляем немного запаса от 64 байт

def safe_callback_data(prefix: str, *args) -> str:
    """Создает безопасный callback_data, который не превышает лимит Telegram."""
    # Соединяем все аргументы через двоеточие
    callback = f"{prefix}:" + ":".join(str(arg) for arg in args)
    
    # Если длина в пределах лимита - возвращаем как есть
    if len(callback) <= MAX_CALLBACK_LENGTH:
        return callback
        
    # Если превышает лимит - обрабатываем особым образом
    logger.warning(f"Callback data exceeds limit: {callback}")
    
    # Обрабатываем разные типы callback_data по-разному
    if prefix == "item":
        action = args[0] if args else ""
        item_name = args[1] if len(args) > 1 else ""
        
        if action in ["v", "view"]:
            # Для просмотра предмета - хешируем имя предмета если оно длинное
            if len(item_name) > 20:
                item_hash = hashlib.md5(item_name.encode()).hexdigest()[:8]
                remaining_args = args[2:] if len(args) > 2 else []
                return f"{prefix}:{action}:{item_hash}:" + ":".join(str(arg) for arg in remaining_args)
    
    elif prefix == "storage":
        action = args[0] if args else ""
        location_id = args[1] if len(args) > 1 else ""
        
        if action in ["items", "view", "edit", "delete", "delete_with_items"]:
            # Для действий с локацией - сохраняем полный ID в сессии и используем короткий хеш
            if location_id and len(location_id) > 10:
                # Сохраняем полный ID в сессию по хешу
                location_hash = hashlib.md5(location_id.encode()).hexdigest()[:10]
                
                # Попытка сохранить маппинг в базе данных
                try:
                    user_ids = db.table.scan(
                        FilterExpression="begins_with(PK, :prefix)",
                        ExpressionAttributeValues={':prefix': 'USER#'}
                    ).get('Items', [])
                    
                    # Берем первого юзера для хранения маппинга (упрощенное решение)
                    if user_ids:
                        user_id = int(user_ids[0]['PK'].split('#')[1])
                        mapping_key = f"HASH_MAP#{location_hash}"
                        
                        # Сохраняем маппинг хеш->полный ID
                        db.table.put_item(Item={
                            'PK': f'SYSTEM',
                            'SK': mapping_key,
                            'orig_id': location_id,
                            'created_at': datetime.now().isoformat()
                        })
                        logger.info(f"Saved hash mapping: {location_hash} -> {location_id}")
                except Exception as e:
                    logger.error(f"Failed to save hash mapping: {e}")
                
                return f"{prefix}:{action}:{location_hash}"
    
    # Общее решение - обрезаем строку до лимита
    return callback[:MAX_CALLBACK_LENGTH]

# Common keyboard actions
ADD_ACTION = "add"
EDIT_ACTION = "edit"
DELETE_ACTION = "delete"
ITEMS_ACTION = "items"
BACK_ACTION = "back"
NEXT_ACTION = "next"
ADD_ITEMS_ACTION = "add_items"
MOVE_ACTION = "move"

# Storage location keyboards
def get_storage_locations_keyboard(locations: List[StorageLocation], 
                                  page: int = 0, 
                                  items_per_page: int = 10,
                                  user_id: Optional[int] = None) -> InlineKeyboardMarkup:
    """Generate keyboard with storage locations."""
    keyboard = []
    
    # Add button for creating a new storage location
    keyboard.append([InlineKeyboardButton("➕ Добавить", callback_data=safe_callback_data("storage", ADD_ACTION))])
    
    # Calculate pagination
    total_pages = (len(locations) + items_per_page - 1) // items_per_page
    start_idx = page * items_per_page
    end_idx = min(start_idx + items_per_page, len(locations))
    
    # Add buttons for each storage location
    for location in locations[start_idx:end_idx]:
        keyboard.append([
            InlineKeyboardButton(
                location.name, 
                callback_data=safe_callback_data("storage", "view", location.id)
            )
        ])
    
    # Add pagination buttons if needed
    if total_pages > 1:
        pagination_row = []
        
        if page > 0:
            pagination_row.append(
                InlineKeyboardButton("⬅️ Назад", callback_data=safe_callback_data("storage", "page", page-1))
            )
            
        if page < total_pages - 1:
            pagination_row.append(
                InlineKeyboardButton("Вперед ➡️", callback_data=safe_callback_data("storage", "page", page+1))
            )
            
        keyboard.append(pagination_row)
    
    # Add trash bin button if it has items
    if user_id:
        logger.info(f"Checking trash bin for user {user_id}")
        trash_bin = db.get_trash_bin(user_id)
        if trash_bin:
            logger.info(f"Found trash bin with {len(trash_bin.items)} items: {trash_bin.items}")
            if trash_bin.items:
                logger.info("Adding trash bin button to keyboard")
                keyboard.append([InlineKeyboardButton("🗑️ Корзина", callback_data=safe_callback_data("storage", "view_trash"))])
            else:
                logger.info("Trash bin is empty, not adding button")
        else:
            logger.warning(f"No trash bin found for user {user_id}")
    
    return InlineKeyboardMarkup(keyboard)

def get_storage_location_actions_keyboard(location_id: str, has_items: bool = False) -> InlineKeyboardMarkup:
    """Generate keyboard with actions for a storage location."""
    if not location_id:
        logger.error("get_storage_location_actions_keyboard called with empty location_id")
        # Создаем базовую клавиатуру для возврата к списку
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Назад к списку", callback_data=safe_callback_data("storage", "list"))]
        ])
        
    keyboard = [
        [InlineKeyboardButton("➕ Добавить вещи", callback_data=safe_callback_data("storage", "add_items", location_id))],
        [InlineKeyboardButton("✏️ Редактировать", callback_data=safe_callback_data("storage", "edit", location_id))],
        [InlineKeyboardButton("📋 Список вещей", callback_data=safe_callback_data("storage", "items", location_id))]
    ]
    
    # Only add delete button if location has no items (or add a different delete flow button)
    if not has_items:
        keyboard.append([InlineKeyboardButton("🗑️ Удалить", callback_data=safe_callback_data("storage", "delete", location_id))])
    else:
        keyboard.append([InlineKeyboardButton("🗑️ Удалить (содержит вещи)", callback_data=safe_callback_data("storage", "delete_with_items", location_id))])
    
    # Add back button
    keyboard.append([InlineKeyboardButton("◀️ Назад к списку", callback_data=safe_callback_data("storage", "list"))])
    
    return InlineKeyboardMarkup(keyboard)

def get_cancel_edit_keyboard(location_id: str) -> InlineKeyboardMarkup:
    """Generate keyboard with only a cancel button for the edit prompt."""
    keyboard = [
        [InlineKeyboardButton("❌ Отмена", callback_data=safe_callback_data("storage", "cancel_edit", location_id))]
    ]
    return InlineKeyboardMarkup(keyboard)

# Item keyboards
def get_items_keyboard(items: List[Item], 
                      page: int = 0, 
                      items_per_page: int = 10,
                      location_id: Optional[str] = None) -> InlineKeyboardMarkup:
    """Generate keyboard with items."""
    keyboard = []
    
    # Ensure items is a list
    items = list(items)
    
    # Calculate pagination
    total_pages = (len(items) + items_per_page - 1) // items_per_page
    start_idx = page * items_per_page
    end_idx = min(start_idx + items_per_page, len(items))
    
    # Add buttons for each item
    for item in items[start_idx:end_idx]:
        # Упрощаем callback_data - только префикс, действие и имя предмета
        callback = safe_callback_data("item", "v", item.name)
        logger.debug(f"Generated item button callback: {callback} for item '{item.name}'") # Логирование
        keyboard.append([
            InlineKeyboardButton(
                item.name,
                callback_data=callback
            )
        ])
    
    # Add pagination buttons if needed
    if total_pages > 1:
        pagination_row = []
        
        # Сокращаем callback_data для пагинации
        if location_id:
            prev_callback = safe_callback_data("item", "pl", location_id, page-1) if page > 0 else None
            next_callback = safe_callback_data("item", "pl", location_id, page+1) if page < total_pages - 1 else None
        else:
            prev_callback = safe_callback_data("item", "pm", page-1) if page > 0 else None
            next_callback = safe_callback_data("item", "pm", page+1) if page < total_pages - 1 else None

        if prev_callback:
            pagination_row.append(
                InlineKeyboardButton("⬅️ Назад", callback_data=prev_callback)
            )
            
        if next_callback:
            pagination_row.append(
                InlineKeyboardButton("Вперед ➡️", callback_data=next_callback)
            )
            
        keyboard.append(pagination_row)
    
    # Add back button if we're in a location context
    if location_id:
        keyboard.append([InlineKeyboardButton("◀️ Назад к месту хранения", callback_data=safe_callback_data("storage", "view", location_id))])
    else:
        # Back button on the main item list goes to the start menu
        keyboard.append([InlineKeyboardButton("◀️ На главную", callback_data="start")])
    
    return InlineKeyboardMarkup(keyboard)

def get_item_actions_keyboard(item_name: str,
                              user_id: int,
                              show_back_to_list_button: bool = True,
                              back_context: Optional[dict] = None,
                              location_id: Optional[str] = None) -> InlineKeyboardMarkup:
    """Generate keyboard with actions for an item, including context-aware back button."""
    # Get the item to find its storage location
    item = db.get_item(user_id, item_name)
    keyboard = [
        [InlineKeyboardButton("✏️ Редактировать", callback_data=safe_callback_data("item", "edit", item_name))],
        [InlineKeyboardButton("🔄 Переместить", callback_data=safe_callback_data("item", "move", item_name))],
    ]
    
    # Add delete or destroy button based on location
    if item and item.storage_location_id == 'trash_bin':
        keyboard.append([InlineKeyboardButton("💥 Уничтожить", callback_data=safe_callback_data("item", "destroy", item_name))])
    else:
        keyboard.append([InlineKeyboardButton("🗑️ Удалить", callback_data=safe_callback_data("item", "delete", item_name))])
    
    # Add "Go to Storage Location" button if item has a storage location and is not in trash bin
    # Use item.storage_location_id directly for the button callback
    actual_location_id = item.storage_location_id if item else None
    if actual_location_id and actual_location_id != 'trash_bin':
        keyboard.append([InlineKeyboardButton("📦 К месту хранения", callback_data=safe_callback_data("storage", "view", actual_location_id))])
    
    if show_back_to_list_button and back_context:
        # Determine the correct list callback based on the back_context
        if back_context.get("type") == "location" and back_context.get("id"):
            # Go back to the specific storage location's item list - используем новый короткий формат
            location_id = back_context['id']
            back_callback_data = safe_callback_data("storage", "items", location_id)
        else:
            # Go back to the main item list
            back_callback_data = safe_callback_data("item", "list")
        keyboard.append([InlineKeyboardButton("◀️ Назад к списку", callback_data=back_callback_data)])
    
    return InlineKeyboardMarkup(keyboard)

# Confirmation keyboards
def get_confirmation_keyboard(action: str, item_id: str) -> InlineKeyboardMarkup:
    """Generate keyboard for confirmation actions."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Да", callback_data=f"confirm:{action}:{item_id}"),
            InlineKeyboardButton("❌ Нет", callback_data=f"cancel:{action}:{item_id}")
        ]
    ]
    
    return InlineKeyboardMarkup(keyboard)

# Move item keyboard
def get_move_item_keyboard(item_name: str, storage_locations: List[StorageLocation],
                          page: int = 0, items_per_page: int = 10) -> InlineKeyboardMarkup:
    """Generate keyboard for moving an item to a different location."""
    keyboard = []
    
    # Calculate pagination
    total_pages = (len(storage_locations) + items_per_page - 1) // items_per_page
    start_idx = page * items_per_page
    end_idx = min(start_idx + items_per_page, len(storage_locations))
    
    # Add buttons for each storage location
    for location in storage_locations[start_idx:end_idx]:
        keyboard.append([
            InlineKeyboardButton(
                location.name,
                callback_data=f"item:move_to:{location.id}"
            )
        ])
    
    # Add pagination buttons if needed
    if total_pages > 1:
        pagination_row = []
        
        if page > 0:
            pagination_row.append(
                InlineKeyboardButton("⬅️ Назад", callback_data=f"item:move_page:{page-1}")
            )
            
        if page < total_pages - 1:
            pagination_row.append(
                InlineKeyboardButton("Вперед ➡️", callback_data=f"item:move_page:{page+1}")
            )
            
        keyboard.append(pagination_row)
    
    # Add cancel button
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data=f"item:view:{item_name}")])
    
    return InlineKeyboardMarkup(keyboard) 