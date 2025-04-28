from typing import Dict, List, Optional, Set
from datetime import datetime
from pydantic import BaseModel, Field


class Item(BaseModel):
    """Model representing an item stored in a storage location."""
    user_id: int
    name: str
    storage_location_id: str
    description: Optional[str] = None
    photo_id: Optional[str] = None
    usage_count: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class StorageLocation(BaseModel):
    """Model representing a storage location."""
    user_id: int
    id: str
    name: str
    photo_id: Optional[str] = None
    items: List[str] = []  # List of item names
    usage_count: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class UserSession(BaseModel):
    """Model for user session state in the bot."""
    user_id: int
    state: str = "IDLE"  # Current state in conversation
    context: Dict = {}  # Additional context for current state
    current_page: Dict = {}  # Track pagination state for different views
    last_updated: str = Field(default_factory=lambda: datetime.now().isoformat())


class UserSettings(BaseModel):
    """Model for user settings."""
    user_id: int
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat()) 