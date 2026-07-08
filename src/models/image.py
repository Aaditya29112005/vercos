import uuid
from typing import Optional

from pydantic import Field, field_validator

from src.models.base import APIBaseModel, current_utc_time
from src.utils.constants import ImageStatus


class Image(APIBaseModel):
    image_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    inspection_id: str
    s3_key: str
    status: ImageStatus = Field(default=ImageStatus.PENDING)
    width: Optional[int] = None
    height: Optional[int] = None
    file_size: int
    content_type: str
    checksum: str
    created_at: str = Field(default_factory=current_utc_time)
    uploaded_at: Optional[str] = None
    ttl: Optional[int] = None
    storage_class: str = Field(default="STANDARD")

    @field_validator("image_id", "inspection_id")
    @classmethod
    def validate_uuids(cls, v: str) -> str:
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError(f"Value must be a valid UUID, got '{v}'")
        return v


class GenerateUploadURLInput(APIBaseModel):
    file_size: int = Field(..., gt=0, description="File size in bytes")
    content_type: str = Field(..., description="MIME type of the image")
    checksum: str = Field(..., description="SHA-256 hash or MD5 checksum")

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, v: str) -> str:
        allowed = ["image/jpeg", "image/png", "image/webp"]
        if v.lower() not in allowed:
            raise ValueError(f"Content-Type '{v}' is not allowed. Must be one of {allowed}")
        return v.lower()


class CompleteUploadInput(APIBaseModel):
    width: int = Field(..., gt=0)
    height: int = Field(..., gt=0)
