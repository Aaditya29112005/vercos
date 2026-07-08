import uuid

import pytest

from src.repository.dynamodb import DynamoDBRepository
from src.repository.s3 import S3Repository
from src.services.inspection_service import InspectionService
from src.services.upload_service import UploadService
from src.utils.constants import EventType, ImageStatus, InspectionStatus
from src.utils.response import EntityNotFoundError, IdempotencyConflictError, OptimisticLockError


def seed_base_data(db_repo: DynamoDBRepository) -> tuple:
    warehouse_id = str(uuid.uuid4())
    drone_id = str(uuid.uuid4())
    db_repo.create_warehouse(warehouse_id, "Test Warehouse", "California")
    db_repo.create_drone(warehouse_id, drone_id, "DJI Phantom 4", "Active")
    return warehouse_id, drone_id


def test_create_inspection_success(mock_db):
    db_repo = DynamoDBRepository()
    w_id, d_id = seed_base_data(db_repo)

    service = InspectionService(db_repo=db_repo)
    result = service.create_inspection(warehouse_id=w_id, drone_id=d_id)

    assert "inspection_id" in result
    assert result["warehouse_id"] == w_id
    assert result["drone_id"] == d_id
    assert result["status"] == InspectionStatus.CREATED
    assert result["version"] == 1

    # Check that a timeline event was created
    timeline = service.get_timeline(result["inspection_id"])
    assert len(timeline) == 1
    assert timeline[0]["event_type"] == EventType.INSPECTION_CREATED


def test_create_inspection_missing_warehouse(mock_db):
    db_repo = DynamoDBRepository()
    service = InspectionService(db_repo=db_repo)

    missing_w_id = str(uuid.uuid4())
    some_d_id = str(uuid.uuid4())

    with pytest.raises(EntityNotFoundError) as exc:
        service.create_inspection(warehouse_id=missing_w_id, drone_id=some_d_id)
    assert f"Warehouse '{missing_w_id}' not found" in str(exc.value)


def test_create_inspection_idempotency(mock_db):
    db_repo = DynamoDBRepository()
    w_id, d_id = seed_base_data(db_repo)

    service = InspectionService(db_repo=db_repo)
    idempotency_key = "test-key-123"

    # First call: creates and caches
    result1 = service.create_inspection(warehouse_id=w_id, drone_id=d_id, idempotency_key=idempotency_key)

    # Second call: should retrieve cached response
    result2 = service.create_inspection(warehouse_id=w_id, drone_id=d_id, idempotency_key=idempotency_key)

    assert result1["inspection_id"] == result2["inspection_id"]

    # Attempting to call again with different payload should raise conflict or return the same if logic permits,
    # but in our service design the lock matches by key, returning the cached response to prevent duplication.
    # If the request parameters are completely different, the idempotency service might conflict depending on implementation.
    # Let's verify that a concurrent run triggers IN_PROGRESS error:
    db_repo.table.put_item(
        Item={
            "PK": "IDEMPOTENCY#locked-key",
            "SK": "RESULT",
            "status": "IN_PROGRESS",
            "ttl": 123456789
        }
    )
    with pytest.raises(IdempotencyConflictError):
        service.create_inspection(warehouse_id=w_id, drone_id=d_id, idempotency_key="locked-key")


def test_optimistic_locking(mock_db):
    db_repo = DynamoDBRepository()
    w_id, d_id = seed_base_data(db_repo)
    service = InspectionService(db_repo=db_repo)

    insp = service.create_inspection(warehouse_id=w_id, drone_id=d_id)
    insp_id = insp["inspection_id"]

    # Update succeeds with correct version (1)
    updated = db_repo.update_inspection_status(
        warehouse_id=w_id, inspection_id=insp_id, new_status=InspectionStatus.UPLOADING, current_version=1
    )
    assert updated["version"] == 2
    assert updated["status"] == InspectionStatus.UPLOADING

    # Update fails with obsolete version (1)
    with pytest.raises(OptimisticLockError):
        db_repo.update_inspection_status(
            warehouse_id=w_id, inspection_id=insp_id, new_status=InspectionStatus.PROCESSING, current_version=1
        )


def test_upload_service_workflow(mock_db, mock_s3_bucket):
    db_repo = DynamoDBRepository()
    s3_repo = S3Repository()
    w_id, d_id = seed_base_data(db_repo)

    insp_service = InspectionService(db_repo=db_repo)
    upload_service = UploadService(db_repo=db_repo, s3_repo=s3_repo)

    # 1. Create inspection
    insp = insp_service.create_inspection(warehouse_id=w_id, drone_id=d_id)
    insp_id = insp["inspection_id"]

    # 2. Generate Upload URL
    url_res = upload_service.generate_upload_url(
        inspection_id=insp_id,
        file_size=1024,
        content_type="image/png",
        checksum="abcd1234checksum"
    )

    assert "uploadUrl" in url_res
    assert url_res["expiresIn"] == 900
    img_id = url_res["imageId"]

    # Verify inspection status moved to UPLOADING
    latest_insp = db_repo.get_inspection(w_id, insp_id)
    assert latest_insp["status"] == InspectionStatus.UPLOADING

    # Verify image is PENDING and has a TTL
    img_metadata = db_repo.get_image(insp_id, img_id)
    assert img_metadata["status"] == ImageStatus.PENDING
    assert img_metadata["ttl"] is not None

    # 3. Complete Upload
    complete_res = upload_service.complete_upload(
        inspection_id=insp_id,
        image_id=img_id,
        width=1920,
        height=1080
    )

    assert complete_res["status"] == ImageStatus.UPLOADED
    assert complete_res["width"] == 1920
    assert complete_res["height"] == 1080

    # Verify TTL was removed from DB item
    updated_img = db_repo.get_image(insp_id, img_id)
    assert "ttl" not in updated_img or updated_img.get("ttl") is None

    # Verify inspection status transitioned to PROCESSING
    updated_insp = db_repo.get_inspection(w_id, insp_id)
    assert updated_insp["status"] == InspectionStatus.PROCESSING

    # 4. Check timeline has all steps documented and cryptographic hashes chained
    timeline = insp_service.get_timeline(insp_id)
    assert len(timeline) == 4
    event_types = [ev["event_type"] for ev in timeline]
    assert EventType.INSPECTION_CREATED in event_types
    assert EventType.UPLOAD_URL_GENERATED in event_types
    assert EventType.IMAGE_UPLOADED in event_types
    assert EventType.INSPECTION_PROCESSING in event_types

    # Cryptographic Hash Chain Tamper-proof validation
    prev_h = "0" * 64
    for ev in timeline:
        assert ev["previous_hash"] == prev_h
        assert ev["hash"] is not None
        prev_h = ev["hash"]

    # 5. Verify Time-Travel snapshot history retrieval
    v1 = db_repo.get_inspection_version(insp_id, 1)
    v2 = db_repo.get_inspection_version(insp_id, 2)
    v3 = db_repo.get_inspection_version(insp_id, 3)

    assert v1 is not None and v1["status"] == InspectionStatus.CREATED
    assert v2 is not None and v2["status"] == InspectionStatus.UPLOADING
    assert v3 is not None and v3["status"] == InspectionStatus.PROCESSING

    # 6. Verify S3 Adaptive Storage strategy selection
    # Small file size (1KB) -> STANDARD
    url_small = upload_service.generate_upload_url(
        inspection_id=insp_id,
        file_size=1024,
        content_type="image/png",
        checksum="chk-small"
    )
    assert url_small["storageClass"] == "STANDARD"

    # Large file size (6MB > 5MB) -> INTELLIGENT_TIERING
    url_large = upload_service.generate_upload_url(
        inspection_id=insp_id,
        file_size=6 * 1024 * 1024,
        content_type="image/png",
        checksum="chk-large"
    )
    assert url_large["storageClass"] == "INTELLIGENT_TIERING"
