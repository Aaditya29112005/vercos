import uuid

from pydantic import Field, field_validator

from src.models.base import APIBaseModel, current_utc_time
from src.utils.constants import InspectionStatus


class Inspection(APIBaseModel):
    organization_id: str = Field(default="DEFAULT-TENANT")
    warehouse_id: str
    drone_id: str
    inspection_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: InspectionStatus = Field(default=InspectionStatus.CREATED)
    version: int = Field(default=1)
    created_at: str = Field(default_factory=current_utc_time)
    updated_at: str = Field(default_factory=current_utc_time)

    @field_validator("warehouse_id", "drone_id", "inspection_id")
    @classmethod
    def validate_uuids(cls, v: str) -> str:
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError(f"Value must be a valid UUID, got '{v}'")
        return v


class CreateInspectionInput(APIBaseModel):
    organization_id: str = Field(default="DEFAULT-TENANT")
    warehouse_id: str
    drone_id: str

    @field_validator("warehouse_id", "drone_id")
    @classmethod
    def validate_uuids(cls, v: str) -> str:
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError(f"Value must be a valid UUID, got '{v}'")
        return v
