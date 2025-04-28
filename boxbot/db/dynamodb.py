import boto3
import uuid
import logging
from typing import Dict, List, Optional, Union, Any
from datetime import datetime
import json

from boxbot.config.config import (
    AWS_ACCESS_KEY_ID, 
    AWS_SECRET_ACCESS_KEY, 
    AWS_REGION, 
    DYNAMODB_TABLE,
    DYNAMODB_ENDPOINT
)
from boxbot.db.models import Item, StorageLocation, UserSession, UserSettings

logger = logging.getLogger(__name__)

class DynamoDBManager:
    """Interface for interacting with DynamoDB for the BoxBot application."""
    
    def __init__(self):
        """Initialize DynamoDB client and resource."""
        self.table_name = DYNAMODB_TABLE
        
        # Configure session
        session_kwargs = {
            'region_name': AWS_REGION
        }
        
        # Add credentials if available
        if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
            session_kwargs['aws_access_key_id'] = AWS_ACCESS_KEY_ID
            session_kwargs['aws_secret_access_key'] = AWS_SECRET_ACCESS_KEY
            
        # Create session
        session = boto3.Session(**session_kwargs)
        
        # Create resource
        resource_kwargs = {}
        if DYNAMODB_ENDPOINT:
            resource_kwargs['endpoint_url'] = DYNAMODB_ENDPOINT
            
        self.dynamodb = session.resource('dynamodb', **resource_kwargs)
        self.table = self.dynamodb.Table(self.table_name)
        
        logger.info(f"DynamoDB manager initialized with table: {self.table_name}")

    def create_table_if_not_exists(self):
        """Create the DynamoDB table if it doesn't exist."""
        try:
            # Check if table exists
            self.dynamodb.meta.client.describe_table(TableName=self.table_name)
            logger.info(f"Table {self.table_name} already exists")
        except self.dynamodb.meta.client.exceptions.ResourceNotFoundException:
            logger.info(f"Creating table {self.table_name}")
            
            # Create table
            table = self.dynamodb.create_table(
                TableName=self.table_name,
                KeySchema=[
                    {
                        'AttributeName': 'PK',
                        'KeyType': 'HASH'  # Partition key
                    },
                    {
                        'AttributeName': 'SK',
                        'KeyType': 'RANGE'  # Sort key
                    }
                ],
                AttributeDefinitions=[
                    {
                        'AttributeName': 'PK',
                        'AttributeType': 'S'
                    },
                    {
                        'AttributeName': 'SK',
                        'AttributeType': 'S'
                    },
                    {
                        'AttributeName': 'GSI1PK',
                        'AttributeType': 'S'
                    },
                    {
                        'AttributeName': 'GSI1SK',
                        'AttributeType': 'S'
                    }
                ],
                GlobalSecondaryIndexes=[
                    {
                        'IndexName': 'GSI1',
                        'KeySchema': [
                            {
                                'AttributeName': 'GSI1PK',
                                'KeyType': 'HASH'
                            },
                            {
                                'AttributeName': 'GSI1SK',
                                'KeyType': 'RANGE'
                            }
                        ],
                        'Projection': {
                            'ProjectionType': 'ALL'
                        },
                        'ProvisionedThroughput': {
                            'ReadCapacityUnits': 5,
                            'WriteCapacityUnits': 5
                        }
                    }
                ],
                ProvisionedThroughput={
                    'ReadCapacityUnits': 5,
                    'WriteCapacityUnits': 5
                }
            )
            
            # Wait for table creation
            table.meta.client.get_waiter('table_exists').wait(TableName=self.table_name)
            logger.info(f"Table {self.table_name} created successfully")
    
    # Storage Location Methods
    def create_storage_location(self, user_id: int, name: str, photo_id: Optional[str] = None) -> StorageLocation:
        """Create a new storage location for a user."""
        location_id = str(uuid.uuid4())
        
        storage_location = StorageLocation(
            user_id=user_id,
            id=location_id,
            name=name,
            photo_id=photo_id
        )
        
        item = {
            'PK': f'USER#{user_id}',
            'SK': f'LOCATION#{location_id}',
            'GSI1PK': f'USER#{user_id}',
            'GSI1SK': f'LOCATION#{name.lower()}#{location_id}',
            'Type': 'StorageLocation',
            'Data': storage_location.json()
        }
        
        self.table.put_item(Item=item)
        logger.info(f"Created storage location '{name}' for user {user_id}")
        
        return storage_location
    
    def get_storage_location(self, user_id: int, location_id: str) -> Optional[StorageLocation]:
        """Get a storage location by ID."""
        response = self.table.get_item(
            Key={
                'PK': f'USER#{user_id}',
                'SK': f'LOCATION#{location_id}'
            }
        )
        
        item = response.get('Item')
        if not item:
            return None
            
        storage_location = StorageLocation.parse_raw(item['Data'])
        return storage_location
    
    def update_storage_location(self, storage_location: StorageLocation) -> StorageLocation:
        """Update an existing storage location."""
        storage_location.updated_at = datetime.now().isoformat()
        
        item = {
            'PK': f'USER#{storage_location.user_id}',
            'SK': f'LOCATION#{storage_location.id}',
            'GSI1PK': f'USER#{storage_location.user_id}',
            'GSI1SK': f'LOCATION#{storage_location.name.lower()}#{storage_location.id}',
            'Type': 'StorageLocation',
            'Data': storage_location.json()
        }
        
        self.table.put_item(Item=item)
        logger.info(f"Updated storage location '{storage_location.name}' for user {storage_location.user_id}")
        
        return storage_location
    
    def delete_storage_location(self, user_id: int, location_id: str) -> bool:
        """Delete a storage location."""
        try:
            self.table.delete_item(
                Key={
                    'PK': f'USER#{user_id}',
                    'SK': f'LOCATION#{location_id}'
                }
            )
            logger.info(f"Deleted storage location {location_id} for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting storage location: {e}")
            return False
    
    def list_storage_locations(self, user_id: int, limit: int = 100, last_evaluated_key: Optional[Dict] = None) -> Dict:
        """List all storage locations for a user with pagination."""
        query_params = {
            'IndexName': 'GSI1',
            'KeyConditionExpression': 'GSI1PK = :pk AND begins_with(GSI1SK, :sk_prefix)',
            'ExpressionAttributeValues': {
                ':pk': f'USER#{user_id}',
                ':sk_prefix': 'LOCATION#'
            },
            'Limit': limit
        }
        
        if last_evaluated_key:
            query_params['ExclusiveStartKey'] = last_evaluated_key
            
        response = self.table.query(**query_params)
        
        locations = []
        for item in response.get('Items', []):
            location = StorageLocation.parse_raw(item['Data'])
            # Exclude trash bin from the list
            if location.id != 'trash_bin':
                locations.append(location)
            
        result = {
            'locations': locations,
            'last_evaluated_key': response.get('LastEvaluatedKey')
        }
        
        return result
    
    def search_storage_locations(self, user_id: int, search_term: str) -> List[StorageLocation]:
        """Search storage locations by name."""
        # This is a simple implementation that fetches all locations and filters on the client side
        # A more efficient implementation would use a search service like Elasticsearch
        response = self.table.query(
            IndexName='GSI1',
            KeyConditionExpression='GSI1PK = :pk AND begins_with(GSI1SK, :sk_prefix)',
            ExpressionAttributeValues={
                ':pk': f'USER#{user_id}',
                ':sk_prefix': 'LOCATION#'
            }
        )
        
        locations = []
        search_term_lower = search_term.lower()
        
        for item in response.get('Items', []):
            location = StorageLocation.parse_raw(item['Data'])
            if search_term_lower in location.name.lower():
                locations.append(location)
                
        return locations
    
    # Item Methods
    def create_item(self, user_id: int, name: str, storage_location_id: str, photo_id: Optional[str] = None) -> Item:
        """Create a new item for a user in a specific storage location."""
        # Check if item with this name already exists for the user
        existing_items = self.search_items(user_id, name)
        if any(item.name.lower() == name.lower() for item in existing_items):
            raise ValueError(f"Item with name '{name}' already exists")
            
        # Create the item
        item_model = Item(
            user_id=user_id,
            name=name,
            storage_location_id=storage_location_id,
            photo_id=photo_id
        )
        
        item_data = {
            'PK': f'USER#{user_id}',
            'SK': f'ITEM#{name.lower()}',
            'GSI1PK': f'USER#{user_id}',
            'GSI1SK': f'ITEM#{name.lower()}',
            'Type': 'Item',
            'LocationId': storage_location_id,
            'Data': item_model.json()
        }
        
        self.table.put_item(Item=item_data)
        logger.info(f"Created item '{name}' for user {user_id} in location {storage_location_id}")
        
        # Update the storage location to include this item
        storage_location = self.get_storage_location(user_id, storage_location_id)
        if storage_location:
            storage_location.items.append(name)
            self.update_storage_location(storage_location)
            
        return item_model
    
    def get_item(self, user_id: int, item_name: str) -> Optional[Item]:
        """Get an item by name."""
        response = self.table.get_item(
            Key={
                'PK': f'USER#{user_id}',
                'SK': f'ITEM#{item_name.lower()}'
            }
        )
        
        item = response.get('Item')
        if not item:
            return None
            
        item_model = Item.parse_raw(item['Data'])
        return item_model
    
    def update_item(self, item: Item) -> Item:
        """Update an existing item."""
        item.updated_at = datetime.now().isoformat()
        
        item_data = {
            'PK': f'USER#{item.user_id}',
            'SK': f'ITEM#{item.name.lower()}',
            'GSI1PK': f'USER#{item.user_id}',
            'GSI1SK': f'ITEM#{item.name.lower()}',
            'Type': 'Item',
            'LocationId': item.storage_location_id,
            'Data': item.json()
        }
        
        self.table.put_item(Item=item_data)
        logger.info(f"Updated item '{item.name}' for user {item.user_id}")
        
        return item
    
    def move_item(self, user_id: int, item_name: str, new_location_id: str) -> Optional[Item]:
        """Move an item to a different storage location."""
        # Get the item
        item = self.get_item(user_id, item_name)
        if not item:
            return None
            
        old_location_id = item.storage_location_id
        
        # Get the old location
        old_location = self.get_storage_location(user_id, old_location_id)
        if old_location and item_name in old_location.items:
            old_location.items.remove(item_name)
            self.update_storage_location(old_location)
            
        # Get the new location
        new_location = self.get_storage_location(user_id, new_location_id)
        if new_location:
            new_location.items.append(item_name)
            self.update_storage_location(new_location)
            
        # Update the item
        item.storage_location_id = new_location_id
        return self.update_item(item)
    
    def delete_item(self, user_id: int, item_name: str) -> bool:
        """Delete an item."""
        # Get the item first to update the storage location
        item = self.get_item(user_id, item_name)
        if item:
            storage_location = self.get_storage_location(user_id, item.storage_location_id)
            if storage_location and item_name in storage_location.items:
                storage_location.items.remove(item_name)
                self.update_storage_location(storage_location)
        
        try:
            self.table.delete_item(
                Key={
                    'PK': f'USER#{user_id}',
                    'SK': f'ITEM#{item_name.lower()}'
                }
            )
            logger.info(f"Deleted item '{item_name}' for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting item: {e}")
            return False
    
    def list_items(self, user_id: int, limit: int = 100, last_evaluated_key: Optional[Dict] = None) -> Dict:
        """List all items for a user with pagination."""
        query_params = {
            'IndexName': 'GSI1',
            'KeyConditionExpression': 'GSI1PK = :pk AND begins_with(GSI1SK, :sk_prefix)',
            'ExpressionAttributeValues': {
                ':pk': f'USER#{user_id}',
                ':sk_prefix': 'ITEM#'
            },
            'Limit': limit
        }
        
        if last_evaluated_key:
            query_params['ExclusiveStartKey'] = last_evaluated_key
            
        response = self.table.query(**query_params)
        
        items = []
        for item in response.get('Items', []):
            item_model = Item.parse_raw(item['Data'])
            items.append(item_model)
            
        result = {
            'items': items,
            'last_evaluated_key': response.get('LastEvaluatedKey')
        }
        
        return result
    
    def list_items_by_location(self, user_id: int, location_id: str, 
                              limit: int = 100, last_evaluated_key: Optional[Dict] = None) -> Dict:
        """List all items in a specific storage location with pagination."""
        # This can be improved with a GSI, but for now we'll scan and filter
        response = self.table.query(
            IndexName='GSI1',
            KeyConditionExpression='GSI1PK = :pk AND begins_with(GSI1SK, :sk_prefix)',
            ExpressionAttributeValues={
                ':pk': f'USER#{user_id}',
                ':sk_prefix': 'ITEM#'
            }
        )
        
        items = []
        for item in response.get('Items', []):
            item_model = Item.parse_raw(item['Data'])
            if item_model.storage_location_id == location_id:
                items.append(item_model)
        
        # Manual pagination
        start_index = 0
        if last_evaluated_key:
            start_index = int(last_evaluated_key.get('index', 0))
        
        end_index = min(start_index + limit, len(items))
        paginated_items = items[start_index:end_index]
        
        last_key = None
        if end_index < len(items):
            last_key = {'index': end_index}
            
        result = {
            'items': paginated_items,
            'last_evaluated_key': last_key
        }
        
        return result
    
    def search_items(self, user_id: int, search_term: str) -> List[Item]:
        """Search items by name and description."""
        response = self.table.query(
            IndexName='GSI1',
            KeyConditionExpression='GSI1PK = :pk AND begins_with(GSI1SK, :sk_prefix)',
            ExpressionAttributeValues={
                ':pk': f'USER#{user_id}',
                ':sk_prefix': 'ITEM#'
            }
        )
        
        items = []
        search_term_lower = search_term.lower()
        
        for item in response.get('Items', []):
            item_model = Item.parse_raw(item['Data'])
            # Search in both name and description
            if (search_term_lower in item_model.name.lower() or 
                (item_model.description and search_term_lower in item_model.description.lower())):
                items.append(item_model)
                
        return items
    
    def increment_usage_count(self, user_id: int, item_name: str) -> Optional[Item]:
        """Increment the usage count for an item and its storage location."""
        item = self.get_item(user_id, item_name)
        if not item:
            return None
            
        # Increment item usage count
        item.usage_count += 1
        self.update_item(item)
        
        # Increment storage location usage count
        location = self.get_storage_location(user_id, item.storage_location_id)
        if location:
            location.usage_count += 1
            self.update_storage_location(location)
            
        return item
    
    def get_top_items(self, user_id: int, limit: int = 10) -> List[Item]:
        """Get the top most used items for a user."""
        response = self.table.query(
            IndexName='GSI1',
            KeyConditionExpression='GSI1PK = :pk AND begins_with(GSI1SK, :sk_prefix)',
            ExpressionAttributeValues={
                ':pk': f'USER#{user_id}',
                ':sk_prefix': 'ITEM#'
            }
        )
        
        items = []
        for item in response.get('Items', []):
            item_model = Item.parse_raw(item['Data'])
            items.append(item_model)
            
        # Sort by usage count in descending order
        items.sort(key=lambda x: x.usage_count, reverse=True)
        
        return items[:limit]
    
    def get_top_locations(self, user_id: int, limit: int = 10) -> List[StorageLocation]:
        """Get the top most used storage locations for a user."""
        response = self.table.query(
            IndexName='GSI1',
            KeyConditionExpression='GSI1PK = :pk AND begins_with(GSI1SK, :sk_prefix)',
            ExpressionAttributeValues={
                ':pk': f'USER#{user_id}',
                ':sk_prefix': 'LOCATION#'
            }
        )
        
        locations = []
        for item in response.get('Items', []):
            location = StorageLocation.parse_raw(item['Data'])
            locations.append(location)
            
        # Sort by usage count in descending order
        locations.sort(key=lambda x: x.usage_count, reverse=True)
        
        return locations[:limit]
    
    # User Session Methods
    def get_user_session(self, user_id: int) -> UserSession:
        """Get or create a user session."""
        response = self.table.get_item(
            Key={
                'PK': f'USER#{user_id}',
                'SK': 'SESSION'
            }
        )
        
        item = response.get('Item')
        if not item:
            # Create new session
            session = UserSession(user_id=user_id)
            self.save_user_session(session)
            return session
            
        session = UserSession.parse_raw(item['Data'])
        return session
    
    def save_user_session(self, session: UserSession) -> UserSession:
        """Save a user session."""
        session.last_updated = datetime.now().isoformat()
        
        item = {
            'PK': f'USER#{session.user_id}',
            'SK': 'SESSION',
            'Type': 'UserSession',
            'Data': session.json()
        }
        
        self.table.put_item(Item=item)
        return session
    
    # User Settings Methods
    def get_user_settings(self, user_id: int) -> UserSettings:
        """Get or create user settings."""
        response = self.table.get_item(
            Key={
                'PK': f'USER#{user_id}',
                'SK': 'SETTINGS'
            }
        )
        
        item = response.get('Item')
        if not item:
            # Create new settings
            settings = UserSettings(user_id=user_id)
            self.save_user_settings(settings)
            return settings
            
        settings = UserSettings.parse_raw(item['Data'])
        return settings
    
    def save_user_settings(self, settings: UserSettings) -> UserSettings:
        """Save user settings."""
        settings.updated_at = datetime.now().isoformat()
        
        item = {
            'PK': f'USER#{settings.user_id}',
            'SK': 'SETTINGS',
            'Type': 'UserSettings',
            'Data': settings.json()
        }
        
        self.table.put_item(Item=item)
        return settings
    
    def move_items_to_trash(self, user_id: int, item_names: List[str]) -> bool:
        """Move items to trash bin. Returns True if successful, False otherwise."""
        try:
            logger.info(f"Moving {len(item_names)} items to trash for user {user_id}")
            logger.info(f"Items to move: {item_names}")
            
            # Get or create trash bin
            trash_bin = self.get_trash_bin(user_id)
            if not trash_bin:
                logger.error(f"Failed to get/create trash bin for user {user_id}")
                return False
            
            logger.info(f"Found trash bin: {trash_bin.id}")
            logger.info(f"Current trash bin items: {trash_bin.items}")
            
            # Move each item to trash
            moved_items = []
            for item_name in item_names:
                item = self.get_item(user_id, item_name)
                if item:
                    logger.info(f"Moving item {item_name} to trash")
                    original_location_id = item.storage_location_id
                    
                    try:
                        # Get the old location and remove the item from it
                        old_location_id = item.storage_location_id
                        if old_location_id and old_location_id != 'trash_bin':
                            old_location = self.get_storage_location(user_id, old_location_id)
                            if old_location and item_name in old_location.items:
                                old_location.items.remove(item_name)
                                self.update_storage_location(old_location)
                                logger.info(f"Removed {item_name} from original location {old_location_id}")
                            elif old_location:
                                 logger.warning(f"Item {item_name} not found in items list of old location {old_location_id}, but present in item data.")
                            else:
                                logger.warning(f"Old location {old_location_id} not found for item {item_name}.")

                        # Move item to trash bin
                        item.storage_location_id = trash_bin.id
                        self.update_item(item) # Updates the item's location attribute

                        # Add to trash bin items list if not already there
                        if item_name not in trash_bin.items:
                            trash_bin.items.append(item_name)
                            moved_items.append((item_name, original_location_id))
                        else:
                            logger.info(f"Item {item_name} already in trash bin")
                    except Exception as e:
                        logger.error(f"Error moving individual item {item_name}: {e}")
                        # Continue with other items but log the error
                else:
                    logger.warning(f"Item {item_name} not found, skipping")
                    
            # Update trash bin
            self.update_storage_location(trash_bin)
            logger.info(f"Updated trash bin, now contains {len(trash_bin.items)} items: {trash_bin.items}")
            return True
        except Exception as e:
            logger.error(f"Error in move_items_to_trash: {e}")
            return False
        
    def get_trash_bin(self, user_id: int) -> Optional[StorageLocation]:
        """Get or create trash bin for a user."""
        logger.info(f"Getting trash bin for user {user_id}")
        
        # Try to get existing trash bin
        response = self.table.get_item(
            Key={
                'PK': f'USER#{user_id}',
                'SK': f'LOCATION#trash_bin'
            }
        )
        
        item = response.get('Item')
        if item:
            logger.info("Found existing trash bin")
            trash_bin = StorageLocation.parse_raw(item['Data'])
            logger.info(f"Trash bin contains {len(trash_bin.items)} items: {trash_bin.items}")
            return trash_bin
            
        # Create new trash bin if not exists
        logger.info("Creating new trash bin")
        trash_bin = StorageLocation(
            user_id=user_id,
            id='trash_bin',
            name='🗑️ Корзина',
            items=[]
        )
        
        item = {
            'PK': f'USER#{user_id}',
            'SK': f'LOCATION#trash_bin',
            'GSI1PK': f'USER#{user_id}',
            'GSI1SK': f'LOCATION#trash_bin',
            'Type': 'StorageLocation',
            'Data': trash_bin.json()
        }
        
        self.table.put_item(Item=item)
        logger.info("Created new trash bin")
        return trash_bin
        
    def clear_trash_bin(self, user_id: int) -> bool:
        """Clear trash bin by deleting all items in it."""
        trash_bin = self.get_trash_bin(user_id)
        if not trash_bin:
            return False
            
        # Delete all items in trash
        for item_name in trash_bin.items:
            self.delete_item(user_id, item_name)
            
        # Clear trash bin items list
        trash_bin.items = []
        self.update_storage_location(trash_bin)
        
        return True 