import time
from typing import Optional

from pydantic import Field

from src.models.base import APIBaseModel, current_utc_time
from src.utils.constants import IDEMPOTENCY_TTL_SECONDS


class IdempotencyRecord(APIBaseModel):
    idempotency_key: str
    status: str  # 'IN_PROGRESS' or 'COMPLETED'
    response_json: Optional[str] = None
    created_at: str = Field(default_factory=current_utc_time)
    ttl: int = Field(
        default_factory=lambda: int(time.time()) + IDEMPOTENCY_TTL_SECONDS
    )
