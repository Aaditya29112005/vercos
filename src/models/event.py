import uuid
from typing import Optional

from pydantic import Field, field_validator

from src.models.base import APIBaseModel, current_utc_time
from src.utils.constants import EventType


class Event(APIBaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    inspection_id: str
    event_type: EventType
    message: str
    timestamp: str = Field(default_factory=current_utc_time)
    payload: dict = Field(default_factory=dict)
    hash: Optional[str] = None
    previous_hash: Optional[str] = None

    @field_validator("event_id", "inspection_id")
    @classmethod
    def validate_uuids(cls, v: str) -> str:
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError(f"Value must be a valid UUID, got '{v}'")
        return v
