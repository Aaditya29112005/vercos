import json
import uuid

from src.handlers import (
    complete_upload,
    create_inspection,
    digital_twin,
    explain_query,
    generate_upload_url,
    get_inspection,
    get_inspection_graph,
    list_drone_inspections,
    list_inspection_images,
    list_inspection_timeline,
    list_warehouse_inspections,
    predictive_capacity,
    replay_inspection,
)
from src.repository.dynamodb import DynamoDBRepository


def seed_base_data(db_repo: DynamoDBRepository) -> tuple:
    warehouse_id = str(uuid.uuid4())
    drone_id = str(uuid.uuid4())
    db_repo.create_warehouse(warehouse_id, "SF Hub", "San Francisco")
    db_repo.create_drone(warehouse_id, drone_id, "DJI Mavic 3", "Active")
    return warehouse_id, drone_id


class MockContext:
    function_name = "test-function"
    memory_limit_in_mb = 128
    aws_request_id = "test-req-id"
    invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:test-function"


def test_handler_create_inspection_success(mock_db):
    db_repo = DynamoDBRepository()
    w_id, d_id = seed_base_data(db_repo)

    event = {
        "body": json.dumps({"warehouse_id": w_id, "drone_id": d_id}),
        "headers": {"Idempotency-Key": "test-key-321"},
        "requestContext": {"requestId": "req-1"}
    }

    response = create_inspection.lambda_handler(event, MockContext())

    assert response["statusCode"] == 201
    body = json.loads(response["body"])
    assert body["success"] is True
    assert body["message"] == "Inspection created successfully"
    assert body["data"]["warehouse_id"] == w_id
    assert body["data"]["drone_id"] == d_id
    assert body["requestId"] == "req-1"


def test_handler_create_inspection_validation_error(mock_db):
    event = {
        "body": json.dumps({
            "warehouse_id": "not-a-uuid",
            "drone_id": str(uuid.uuid4())
        }),
        "requestContext": {"requestId": "req-2"}
    }

    response = create_inspection.lambda_handler(event, MockContext())

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["success"] is False
    assert "validation failed" in body["message"].lower()
    assert len(body["data"]["errors"]) > 0
    assert body["data"]["errors"][0]["field"] == "warehouse_id"


def test_handler_list_warehouse_inspections_success(mock_db):
    db_repo = DynamoDBRepository()
    w_id, d_id = seed_base_data(db_repo)

    # Pre-populate an inspection
    insp_id = str(uuid.uuid4())
    db_repo.create_inspection(
        type("Insp", (object,), {
            "organization_id": "DEFAULT-TENANT",
            "warehouse_id": w_id,
            "drone_id": d_id,
            "inspection_id": insp_id,
            "status": "CREATED",
            "version": 1,
            "model_dump": lambda s: {
                "organization_id": "DEFAULT-TENANT",
                "warehouse_id": w_id,
                "drone_id": d_id,
                "inspection_id": insp_id,
                "status": "CREATED",
                "version": 1,
                "created_at": "2026-07-08T00:00:00Z",
                "updated_at": "2026-07-08T00:00:00Z"
            }
        })()
    )

    event = {
        "pathParameters": {"id": w_id},
        "queryStringParameters": {"limit": "5"},
        "requestContext": {"requestId": "req-3"}
    }

    response = list_warehouse_inspections.lambda_handler(event, MockContext())
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["success"] is True
    assert len(body["data"]["inspections"]) == 1
    assert body["data"]["inspections"][0]["inspection_id"] == insp_id


def test_handler_generate_upload_url_invalid_mime(mock_db, mock_s3_bucket):
    db_repo = DynamoDBRepository()
    w_id, d_id = seed_base_data(db_repo)

    # Pre-populate an inspection
    insp_id = str(uuid.uuid4())
    db_repo.create_inspection(
        type("Insp", (object,), {
            "organization_id": "DEFAULT-TENANT",
            "warehouse_id": w_id,
            "drone_id": d_id,
            "inspection_id": insp_id,
            "status": "CREATED",
            "version": 1,
            "model_dump": lambda s: {
                "organization_id": "DEFAULT-TENANT",
                "warehouse_id": w_id,
                "drone_id": d_id,
                "inspection_id": insp_id,
                "status": "CREATED",
                "version": 1,
                "created_at": "2026-07-08T00:00:00Z",
                "updated_at": "2026-07-08T00:00:00Z"
            }
        })()
    )

    event = {
        "pathParameters": {"id": insp_id},
        "body": json.dumps({
            "file_size": 50000,
            "content_type": "application/pdf",  # Invalid type
            "checksum": "chk123"
        }),
        "requestContext": {"requestId": "req-4"}
    }

    response = generate_upload_url.lambda_handler(event, MockContext())
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["success"] is False
    assert "content-type" in body["data"]["errors"][0]["message"].lower()


def test_handler_complete_upload_success(mock_db, mock_s3_bucket):
    db_repo = DynamoDBRepository()
    w_id, d_id = seed_base_data(db_repo)

    # 1. Create Inspection
    insp_id = str(uuid.uuid4())
    db_repo.create_inspection(
        type("Insp", (object,), {
            "organization_id": "DEFAULT-TENANT",
            "warehouse_id": w_id,
            "drone_id": d_id,
            "inspection_id": insp_id,
            "status": "CREATED",
            "version": 1,
            "model_dump": lambda s: {
                "organization_id": "DEFAULT-TENANT",
                "warehouse_id": w_id,
                "drone_id": d_id,
                "inspection_id": insp_id,
                "status": "CREATED",
                "version": 1,
                "created_at": "2026-07-08T00:00:00Z",
                "updated_at": "2026-07-08T00:00:00Z"
            }
        })()
    )

    # 2. Add pending image
    img_id = str(uuid.uuid4())
    db_repo.save_image_upload(
        type("Img", (object,), {
            "inspection_id": insp_id,
            "image_id": img_id,
            "model_dump": lambda s: {
                "inspection_id": insp_id,
                "image_id": img_id,
                "s3_key": "dummy/key",
                "status": "PENDING",
                "file_size": 1024,
                "content_type": "image/jpeg",
                "checksum": "dummychecksum",
                "ttl": 1234567,
                "created_at": "2026-07-08T00:00:00Z"
            }
        })()
    )

    # 3. Call webhook complete upload
    event = {
        "pathParameters": {
            "id": insp_id,
            "image_id": img_id
        },
        "body": json.dumps({
            "width": 1920,
            "height": 1080
        }),
        "requestContext": {"requestId": "req-5"}
    }

    response = complete_upload.lambda_handler(event, MockContext())
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["success"] is True
    assert body["data"]["status"] == "UPLOADED"
    assert body["data"]["width"] == 1920
    assert body["data"]["height"] == 1080

    # 4. Check listing timeline endpoint returns history successfully
    timeline_event = {
        "pathParameters": {"id": insp_id},
        "requestContext": {"requestId": "req-6"}
    }
    tl_response = list_inspection_timeline.lambda_handler(timeline_event, MockContext())
    assert tl_response["statusCode"] == 200
    tl_body = json.loads(tl_response["body"])
    assert len(tl_body["data"]["timeline"]) > 0


def test_handler_list_drone_inspections_success(mock_db):
    db_repo = DynamoDBRepository()
    w_id, d_id = seed_base_data(db_repo)

    event = {
        "pathParameters": {"id": d_id},
        "queryStringParameters": {"limit": "5"},
        "requestContext": {"requestId": "req-7"}
    }

    response = list_drone_inspections.lambda_handler(event, MockContext())
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["success"] is True
    assert "inspections" in body["data"]


def test_handler_list_inspection_images_success(mock_db):
    db_repo = DynamoDBRepository()
    w_id, d_id = seed_base_data(db_repo)

    # Pre-populate an inspection
    insp_id = str(uuid.uuid4())
    db_repo.create_inspection(
        type("Insp", (object,), {
            "organization_id": "DEFAULT-TENANT",
            "warehouse_id": w_id,
            "drone_id": d_id,
            "inspection_id": insp_id,
            "status": "CREATED",
            "version": 1,
            "model_dump": lambda s: {
                "organization_id": "DEFAULT-TENANT",
                "warehouse_id": w_id,
                "drone_id": d_id,
                "inspection_id": insp_id,
                "status": "CREATED",
                "version": 1,
                "created_at": "2026-07-08T00:00:00Z",
                "updated_at": "2026-07-08T00:00:00Z"
            }
        })()
    )

    event = {
        "pathParameters": {"id": insp_id},
        "requestContext": {"requestId": "req-8"}
    }

    response = list_inspection_images.lambda_handler(event, MockContext())
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["success"] is True
    assert "images" in body["data"]


def test_handler_get_inspection_success(mock_db):
    db_repo = DynamoDBRepository()
    w_id, d_id = seed_base_data(db_repo)

    # Pre-populate inspection
    insp_id = str(uuid.uuid4())
    db_repo.create_inspection(
        type("Insp", (object,), {
            "organization_id": "DEFAULT-TENANT",
            "warehouse_id": w_id,
            "drone_id": d_id,
            "inspection_id": insp_id,
            "status": "CREATED",
            "version": 1,
            "model_dump": lambda s: {
                "organization_id": "DEFAULT-TENANT",
                "warehouse_id": w_id,
                "drone_id": d_id,
                "inspection_id": insp_id,
                "status": "CREATED",
                "version": 1,
                "created_at": "2026-07-08T00:00:00Z",
                "updated_at": "2026-07-08T00:00:00Z"
            }
        })()
    )

    event = {
        "pathParameters": {"id": insp_id},
        "queryStringParameters": {"version": "1"},
        "requestContext": {"requestId": "req-9"}
    }

    response = get_inspection.lambda_handler(event, MockContext())
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["success"] is True
    assert body["data"]["inspection_id"] == insp_id
    assert body["data"]["version"] == 1


def test_handler_get_inspection_graph_success(mock_db):
    db_repo = DynamoDBRepository()
    w_id, d_id = seed_base_data(db_repo)

    # Pre-populate inspection
    insp_id = str(uuid.uuid4())
    db_repo.create_inspection(
        type("Insp", (object,), {
            "organization_id": "DEFAULT-TENANT",
            "warehouse_id": w_id,
            "drone_id": d_id,
            "inspection_id": insp_id,
            "status": "CREATED",
            "version": 1,
            "model_dump": lambda s: {
                "organization_id": "DEFAULT-TENANT",
                "warehouse_id": w_id,
                "drone_id": d_id,
                "inspection_id": insp_id,
                "status": "CREATED",
                "version": 1,
                "created_at": "2026-07-08T00:00:00Z",
                "updated_at": "2026-07-08T00:00:00Z"
            }
        })()
    )

    event = {
        "pathParameters": {"id": insp_id},
        "requestContext": {"requestId": "req-10"}
    }

    response = get_inspection_graph.lambda_handler(event, MockContext())
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["success"] is True
    assert "warehouse" in body["data"]
    assert "drone" in body["data"]
    assert "inspection" in body["data"]


def test_handler_replay_inspection_success(mock_db):
    db_repo = DynamoDBRepository()
    w_id, d_id = seed_base_data(db_repo)

    # Pre-populate inspection
    insp_id = str(uuid.uuid4())
    db_repo.create_inspection(
        type("Insp", (object,), {
            "organization_id": "DEFAULT-TENANT",
            "warehouse_id": w_id,
            "drone_id": d_id,
            "inspection_id": insp_id,
            "status": "CREATED",
            "version": 1,
            "model_dump": lambda s: {
                "organization_id": "DEFAULT-TENANT",
                "warehouse_id": w_id,
                "drone_id": d_id,
                "inspection_id": insp_id,
                "status": "CREATED",
                "version": 1,
                "created_at": "2026-07-08T00:00:00Z",
                "updated_at": "2026-07-08T00:00:00Z"
            }
        })()
    )

    event = {
        "pathParameters": {"id": insp_id},
        "requestContext": {"requestId": "req-11"}
    }

    response = replay_inspection.lambda_handler(event, MockContext())
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["success"] is True
    assert "replay_timeline" in body["data"]


def test_handler_explain_query_success(mock_db):
    db_repo = DynamoDBRepository()
    w_id, d_id = seed_base_data(db_repo)

    # Pre-populate inspection
    insp_id = str(uuid.uuid4())
    db_repo.create_inspection(
        type("Insp", (object,), {
            "organization_id": "DEFAULT-TENANT",
            "warehouse_id": w_id,
            "drone_id": d_id,
            "inspection_id": insp_id,
            "status": "CREATED",
            "version": 1,
            "model_dump": lambda s: {
                "organization_id": "DEFAULT-TENANT",
                "warehouse_id": w_id,
                "drone_id": d_id,
                "inspection_id": insp_id,
                "status": "CREATED",
                "version": 1,
                "created_at": "2026-07-08T00:00:00Z",
                "updated_at": "2026-07-08T00:00:00Z"
            }
        })()
    )

    event = {
        "pathParameters": {"id": insp_id},
        "requestContext": {"requestId": "req-12"}
    }

    response = explain_query.lambda_handler(event, MockContext())
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["success"] is True
    assert "activeQueryPath" in body["data"]


def test_handler_digital_twin_success(mock_db):
    db_repo = DynamoDBRepository()
    w_id, d_id = seed_base_data(db_repo)

    event = {
        "pathParameters": {"id": w_id},
        "queryStringParameters": {"organization_id": "DEFAULT-TENANT"},
        "requestContext": {"requestId": "req-13"}
    }

    response = digital_twin.lambda_handler(event, MockContext())
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["success"] is True
    assert "drones" in body["data"]
    assert body["data"]["warehouse_id"] == w_id


def test_handler_predictive_capacity_success(mock_db):
    db_repo = DynamoDBRepository()
    w_id, d_id = seed_base_data(db_repo)

    event = {
        "pathParameters": {"id": w_id},
        "queryStringParameters": {"organization_id": "DEFAULT-TENANT"},
        "requestContext": {"requestId": "req-14"}
    }

    response = predictive_capacity.lambda_handler(event, MockContext())
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["success"] is True
    assert "projections" in body["data"]

