import json
import os
import sys
import uuid
import boto3
from moto import mock_aws

# Add root folder to sys path so we can import src modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.handlers import (
    create_inspection,
    list_warehouse_inspections,
    list_drone_inspections,
    generate_upload_url,
    complete_upload,
    list_inspection_images,
    list_inspection_timeline,
    get_inspection,
    get_inspection_graph,
    replay_inspection,
    explain_query,
    digital_twin,
    predictive_capacity,
)


def print_header(title):
    print("\n" + "=" * 80)
    print(f" {title} ".center(80, "="))
    print("=" * 80)


def print_json(data):
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            pass
    print(json.dumps(data, indent=2))


def run_demo():
    # Setup standard environmental variables for testing
    os.environ["TABLE_NAME"] = "DroneInspectionTable"
    os.environ["BUCKET_NAME"] = "drone-inspection-bucket"
    os.environ["AWS_REGION"] = "us-east-1"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    os.environ["AWS_ACCESS_KEY_ID"] = "demo_key"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "demo_secret"

    print("Initializing local mocked AWS environment using Moto...")

    with mock_aws():
        # Setup DynamoDB & S3 resource pools
        db = boto3.resource("dynamodb", region_name="us-east-1")
        s3 = boto3.client("s3", region_name="us-east-1")

        # 1. Create DynamoDB Single-Table Schema
        table = db.create_table(
            TableName="DroneInspectionTable",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"}
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"}
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI1",
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"}
                    ],
                    "Projection": {"ProjectionType": "ALL"}
                },
                {
                    "IndexName": "InvertedIndex",
                    "KeySchema": [
                        {"AttributeName": "SK", "KeyType": "HASH"},
                        {"AttributeName": "PK", "KeyType": "RANGE"}
                    ],
                    "Projection": {"ProjectionType": "ALL"}
                }
            ],
            BillingMode="PAY_PER_REQUEST"
        )
        table.meta.client.get_waiter("table_exists").wait(TableName="DroneInspectionTable")
        print("Mock DynamoDB Table 'DroneInspectionTable' Created.")

        # 2. Create S3 Private Bucket
        s3.create_bucket(Bucket="drone-inspection-bucket")
        print("Mock S3 Bucket 'drone-inspection-bucket' Created.")

        # 3. Seed Mock Warehouse & Drone Data
        from src.repository.dynamodb import DynamoDBRepository
        repo = DynamoDBRepository()

        warehouse_id = str(uuid.uuid4())
        drone_id = str(uuid.uuid4())
        org_id = "ORG-VECROS-INC"

        repo.create_warehouse(warehouse_id, "Texas Hub (San Antonio)", "San Antonio, TX", org_id=org_id)
        repo.create_drone(warehouse_id, drone_id, "DJI Matrice 300 RTK", "Active", org_id=org_id)
        print(f"Base data seeded. Organization: {org_id}, Warehouse: {warehouse_id}, Drone: {drone_id}")

        # Setup standard mock Lambda Context
        class MockContext:
            function_name = "drone-inspection-demo"
            memory_limit_in_mb = 128
            aws_request_id = "demo-request-id-1234"
            invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:drone-inspection-demo"

        context = MockContext()

        # Step 1: Idempotent Create Inspection - First Call (Sets up Organization partition)
        print_header("1. POST /v1/inspections (Multi-Tenant Org: ORG-VECROS-INC)")
        payload = {"warehouse_id": warehouse_id, "drone_id": drone_id, "organization_id": org_id}
        event = {
            "body": json.dumps(payload),
            "headers": {"Idempotency-Key": "key-abc"},
            "requestContext": {"requestId": "req-1"}
        }
        res1 = create_inspection.lambda_handler(event, context)
        print(f"HTTP Status: {res1['statusCode']}")
        print_json(res1["body"])

        # Parse Inspection ID
        body_dict = json.loads(res1["body"])
        inspection_id = body_dict["data"]["inspection_id"]

        # Step 2: Request Upload URL (Triggers S3 Adaptive tiering standard class)
        print_header(f"2. POST /v1/inspections/{inspection_id}/upload-url (Small Image: 10KB -> Standard)")
        upload_payload_small = {
            "file_size": 10240,
            "content_type": "image/png",
            "checksum": "sha256-small-123"
        }
        event = {
            "pathParameters": {"id": inspection_id},
            "body": json.dumps(upload_payload_small),
            "requestContext": {"requestId": "req-2"}
        }
        res2 = generate_upload_url.lambda_handler(event, context)
        print_json(res2["body"])

        res2_body = json.loads(res2["body"])
        image_id_small = res2_body["data"]["imageId"]
        s3_key_small = res2_body["data"]["s3Key"]

        # Step 3: Request Upload URL (Triggers S3 Adaptive tiering intelligent-tiering class)
        print_header(f"3. POST /v1/inspections/{inspection_id}/upload-url (Large Image: 8MB -> Intelligent-Tiering)")
        upload_payload_large = {
            "file_size": 8 * 1024 * 1024,
            "content_type": "image/png",
            "checksum": "sha256-large-456"
        }
        event = {
            "pathParameters": {"id": inspection_id},
            "body": json.dumps(upload_payload_large),
            "requestContext": {"requestId": "req-3"}
        }
        res3 = generate_upload_url.lambda_handler(event, context)
        print_json(res3["body"])

        # Step 4: Simulate S3 uploads
        print_header("4. Uploading items to S3...")
        s3.put_object(
            Bucket="drone-inspection-bucket",
            Key=s3_key_small,
            Body=b"small mock",
            ContentType="image/png"
        )
        print(f"Uploaded S3 key: {s3_key_small}")

        # Step 5: Confirm S3 Upload Webhook (Saves updated version snapshot)
        print_header(f"5. POST /v1/inspections/{inspection_id}/images/{image_id_small}/complete")
        complete_payload = {"width": 1920, "height": 1080}
        event = {
            "pathParameters": {"id": inspection_id, "image_id": image_id_small},
            "body": json.dumps(complete_payload),
            "requestContext": {"requestId": "req-5"}
        }
        res5 = complete_upload.lambda_handler(event, context)
        print_json(res5["body"])

        # Step 6: Single-Point Knowledge Graph joins
        print_header(f"6. GET /v1/inspections/{inspection_id}/graph (Knowledge Graph & Live Metrics)")
        event = {
            "pathParameters": {"id": inspection_id},
            "requestContext": {"requestId": "req-6"}
        }
        res6 = get_inspection_graph.lambda_handler(event, context)
        print_json(res6["body"])

        # Step 7: Time-Travel snapshot lookups
        print_header(f"7. GET /v1/inspections/{inspection_id}?version=1 (Time-Travel: Initial state)")
        event = {
            "pathParameters": {"id": inspection_id},
            "queryStringParameters": {"version": "1"},
            "requestContext": {"requestId": "req-7"}
        }
        res7_v1 = get_inspection.lambda_handler(event, context)
        print_json(res7_v1["body"])

        print_header(f"7b. GET /v1/inspections/{inspection_id}?version=3 (Time-Travel: Processing state)")
        event = {
            "pathParameters": {"id": inspection_id},
            "queryStringParameters": {"version": "3"},
            "requestContext": {"requestId": "req-7b"}
        }
        res7_v3 = get_inspection.lambda_handler(event, context)
        print_json(res7_v3["body"])

        # Step 8: Playback simulation with offsets
        print_header(f"8. GET /v1/inspections/{inspection_id}/replay (Event Playback offset seconds)")
        event = {
            "pathParameters": {"id": inspection_id},
            "requestContext": {"requestId": "req-8"}
        }
        res8 = replay_inspection.lambda_handler(event, context)
        print_json(res8["body"])

        # Step 9: Database query plans debug explainer
        print_header(f"9. GET /v1/inspections/{inspection_id}/explain (Query Explain Plan)")
        event = {
            "pathParameters": {"id": inspection_id},
            "requestContext": {"requestId": "req-9"}
        }
        res9 = explain_query.lambda_handler(event, context)
        print_json(res9["body"])

        # Step 10: Warehouse Digital Twin fetch
        print_header(f"10. GET /v1/warehouses/{warehouse_id}/digital-twin (Asset batteries & status twins)")
        event = {
            "pathParameters": {"id": warehouse_id},
            "queryStringParameters": {"organization_id": org_id},
            "requestContext": {"requestId": "req-10"}
        }
        res10 = digital_twin.lambda_handler(event, context)
        print_json(res10["body"])

        # Step 11: Warehouse storage forecast capacity projection
        print_header(f"11. GET /v1/warehouses/{warehouse_id}/predictive-capacity (Predictive forecaster)")
        event = {
            "pathParameters": {"id": warehouse_id},
            "queryStringParameters": {"organization_id": org_id},
            "requestContext": {"requestId": "req-11"}
        }
        res11 = predictive_capacity.lambda_handler(event, context)
        print_json(res11["body"])


if __name__ == "__main__":
    run_demo()
