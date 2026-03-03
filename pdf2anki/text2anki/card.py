import uuid
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class AnkiCard:
    """
    Represents a single Anki card with its core data and metadata.
    This is the central data model for the SSOT (Single Source of Truth).
    """
    front: str
    back: str
    guid: str = field(default_factory=lambda: str(uuid.uuid4()))
    collection: Optional[str] = None
    category: Optional[str] = None
    sort_field: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self):
        """Serializes the card object to a dictionary for JSON storage."""
        return {
            "guid": self.guid,
            "front": self.front,
            "back": self.back,
            "collection": self.collection,
            "category": self.category,
            "sort_field": self.sort_field,
            "tags": self.tags,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: dict):
        """Deserializes a dictionary back into a card object."""
        # Convert ISO format strings back to datetime objects
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if isinstance(data.get("updated_at"), str):
            data["updated_at"] = datetime.fromisoformat(data["updated_at"])
        
        return cls(**data)

    def __post_init__(self):
        """Ensure timestamps are set correctly after initialization."""
        if not self.created_at:
            self.created_at = datetime.now()
        if not self.updated_at:
            self.updated_at = datetime.now()
