from enum import Enum


class InspectionStatus(str, Enum):
    CREATED = "CREATED"
    UPLOADING = "UPLOADING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ImageStatus(str, Enum):
    PENDING = "PENDING"
    UPLOADED = "UPLOADED"
    FAILED = "FAILED"


class EventType(str, Enum):
    INSPECTION_CREATED = "InspectionCreated"
    UPLOAD_URL_GENERATED = "UploadURLGenerated"
    IMAGE_UPLOADED = "ImageUploaded"
    INSPECTION_PROCESSING = "InspectionProcessing"
    INSPECTION_COMPLETED = "InspectionCompleted"
    INSPECTION_FAILED = "InspectionFailed"


DEFAULT_PAGINATION_LIMIT = 10
IDEMPOTENCY_TTL_SECONDS = 86400  # 24 hours
DEFAULT_URL_EXPIRY_SECONDS = 900  # 15 minutes
