import time
from typing import Optional

from src.models.event import Event
from src.models.image import Image
from src.models.base import current_utc_time
from src.repository.dynamodb import DynamoDBRepository
from src.repository.s3 import S3Repository, build_s3_key
from src.utils.constants import EventType, ImageStatus, InspectionStatus
from aws_lambda_powertools.metrics import MetricUnit
from src.utils.logger import logger, metrics
from src.utils.response import EntityNotFoundError


class UploadService:
    def __init__(
        self,
        db_repo: Optional[DynamoDBRepository] = None,
        s3_repo: Optional[S3Repository] = None,
    ):
        self.db_repo = db_repo or DynamoDBRepository()
        self.s3_repo = s3_repo or S3Repository()

    def generate_upload_url(
        self, inspection_id: str, file_size: int, content_type: str, checksum: str
    ) -> dict:
        """
        Validates the inspection, generates a pre-signed S3 URL, and stores a pending upload tracker.
        Applies adaptive S3 storage class tiering based on file size thresholds (>5MB is Intelligent-Tiering).
        """
        # 1. Look up inspection to get the associated warehouse
        inspection_item = self.db_repo.get_inspection_by_id_only(inspection_id)
        if not inspection_item:
            raise EntityNotFoundError(f"Inspection '{inspection_id}' not found.")

        # Record Presigned URL request metric
        try:
            metrics.add_metric(name="PresignedURLRequests", unit=MetricUnit.Count, value=1)
        except Exception:
            pass

        warehouse_id = inspection_item["warehouse_id"]
        org_id = inspection_item.get("organization_id", "DEFAULT-TENANT")

        # Adaptive storage strategy decision
        # > 5MB (5242880 bytes) uses Intelligent-Tiering, else Standard
        storage_class = "STANDARD"
        if file_size > 5242880:
            storage_class = "INTELLIGENT_TIERING"
            logger.info(f"Adaptive storage triggered: Image size {file_size} > 5MB. Using Intelligent-Tiering.")

        # 2. Build model instance for pending image record
        # A 15-minute TTL from now is added to the record
        ttl_expiry = int(time.time()) + 900
        image = Image(
            inspection_id=inspection_id,
            s3_key="",  # Will fill below
            file_size=file_size,
            content_type=content_type,
            checksum=checksum,
            status=ImageStatus.PENDING,
            ttl=ttl_expiry,
            storage_class=storage_class
        )

        # Build clean S3 key
        s3_key = build_s3_key(warehouse_id, inspection_id, image.image_id, content_type, org_id)
        image.s3_key = s3_key

        # 3. Save pending image tracker in DynamoDB
        self.db_repo.save_image_upload(image)

        # 4. Generate S3 pre-signed PUT URL
        upload_url = self.s3_repo.generate_upload_url(
            key=s3_key, expires_in=900, content_type=content_type
        )

        # 5. Record Audit Event for generated URL
        event = Event(
            inspection_id=inspection_id,
            event_type=EventType.UPLOAD_URL_GENERATED,
            message=f"Pre-signed upload URL generated for image '{image.image_id}' (Tier: {storage_class}). Expiry 15 mins.",
            payload={
                "image_id": image.image_id,
                "s3_key": s3_key,
                "file_size": file_size,
                "content_type": content_type,
                "storage_class": storage_class
            }
        )
        self.db_repo.create_event(event)

        # 6. Update inspection status to UPLOADING if it is currently CREATED
        current_status = inspection_item.get("status")
        if current_status == InspectionStatus.CREATED:
            try:
                self.db_repo.update_inspection_status(
                    warehouse_id=warehouse_id,
                    inspection_id=inspection_id,
                    new_status=InspectionStatus.UPLOADING,
                    current_version=inspection_item["version"],
                    org_id=org_id
                )
            except Exception as e:
                logger.warning(f"Could not advance status of inspection {inspection_id} to UPLOADING: {e}")

        return {
            "imageId": image.image_id,
            "uploadUrl": upload_url,
            "s3Key": s3_key,
            "expiresIn": 900,
            "storageClass": storage_class
        }

    def complete_upload(self, inspection_id: str, image_id: str, width: int, height: int) -> dict:
        """
        Confirms S3 upload has completed, updates the image record, and updates the inspection state.
        """
        # 1. Fetch inspection to retrieve warehouse
        inspection_item = self.db_repo.get_inspection_by_id_only(inspection_id)
        if not inspection_item:
            raise EntityNotFoundError(f"Inspection '{inspection_id}' not found.")

        warehouse_id = inspection_item["warehouse_id"]
        org_id = inspection_item.get("organization_id", "DEFAULT-TENANT")

        # 2. Fetch image metadata
        image_item = self.db_repo.get_image(inspection_id, image_id)
        if not image_item:
            raise EntityNotFoundError(
                f"Image '{image_id}' not found for inspection '{inspection_id}'."
            )

        # Idempotency check: if already completed, return cached response
        if image_item.get("status") == ImageStatus.UPLOADED:
            logger.info(f"Image '{image_id}' is already marked as UPLOADED. Returning success.")
            return {
                "imageId": image_id,
                "status": ImageStatus.UPLOADED,
                "width": image_item.get("width"),
                "height": image_item.get("height"),
                "uploadedAt": image_item.get("uploaded_at")
            }

        # 3. Update Image state in DynamoDB (this removes the TTL attribute)
        now_time = current_utc_time()
        self.db_repo.update_image_upload_complete(
            inspection_id=inspection_id,
            image_id=image_id,
            width=width,
            height=height,
            uploaded_at=now_time
        )

        # Record image upload and latency metrics
        try:
            metrics.add_metric(name="ImageUploads", unit=MetricUnit.Count, value=1)
            if image_item and image_item.get("created_at"):
                from datetime import datetime
                try:
                    created_dt = datetime.fromisoformat(image_item["created_at"].replace("Z", "+00:00"))
                    now_dt = datetime.fromisoformat(now_time.replace("Z", "+00:00"))
                    latency_ms = int((now_dt - created_dt).total_seconds() * 1000)
                    metrics.add_metric(name="UploadLatency", unit=MetricUnit.Milliseconds, value=latency_ms)
                except Exception:
                    pass
        except Exception:
            pass

        # 4. Log audit log for completed image upload
        event = Event(
            inspection_id=inspection_id,
            event_type=EventType.IMAGE_UPLOADED,
            message=f"Image upload completed for image '{image_id}' ({width}x{height}).",
            payload={
                "image_id": image_id,
                "width": width,
                "height": height,
                "uploaded_at": now_time
            }
        )
        self.db_repo.create_event(event)

        # 5. Advance Inspection Status from UPLOADING to PROCESSING
        current_status = inspection_item.get("status")
        if current_status in [InspectionStatus.CREATED, InspectionStatus.UPLOADING]:
            try:
                # Reload inspection to get latest version string
                latest_inspection = self.db_repo.get_inspection(warehouse_id, inspection_id, org_id)
                if latest_inspection:
                    self.db_repo.update_inspection_status(
                        warehouse_id=warehouse_id,
                        inspection_id=inspection_id,
                        new_status=InspectionStatus.PROCESSING,
                        current_version=latest_inspection["version"],
                        org_id=org_id
                    )

                    # Record Transition event
                    processing_event = Event(
                        inspection_id=inspection_id,
                        event_type=EventType.INSPECTION_PROCESSING,
                        message="Inspection moved to PROCESSING state (AI Analysis initiated).",
                        payload={"status": InspectionStatus.PROCESSING}
                    )
                    self.db_repo.create_event(processing_event)
            except Exception as e:
                logger.warning(f"Could not advance status of inspection {inspection_id} to PROCESSING: {e}")

        return {
            "imageId": image_id,
            "status": ImageStatus.UPLOADED,
            "width": width,
            "height": height,
            "uploadedAt": now_time
        }

    def list_inspection_images(self, inspection_id: str) -> dict:
        """Lists all uploaded images for the given inspection."""
        inspection = self.db_repo.get_inspection_by_id_only(inspection_id)
        if not inspection:
            raise EntityNotFoundError(f"Inspection '{inspection_id}' not found.")

        images = self.db_repo.list_inspection_images(inspection_id)
        cleaned_images = []
        for img in images:
            cleaned_images.append(
                {k: v for k, v in img.items() if k not in ["PK", "SK", "EntityType"]}
            )
        return {"images": cleaned_images}
