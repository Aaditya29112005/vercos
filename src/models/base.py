from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict


def current_utc_time() -> str:
    """Generates standard ISO 8601 UTC timestamp string ending in 'Z'."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class APIBaseModel(BaseModel):
    """Base Pydantic model with default configuration."""

    model_config = ConfigDict(
        populate_by_name=True,
        validate_assignment=True,
        extra="ignore",
    )
