import os
import sys
import boto3
from botocore.exceptions import ClientError

# Ensure src/ is in the import path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.repository.dynamodb import DynamoDBRepository
from src.utils.logger import logger


def init_and_seed():
    table_name = os.environ.get("TABLE_NAME", "DroneInspectionTable")
    endpoint_url = os.environ.get("DYNAMODB_ENDPOINT_URL")
    region_name = os.environ.get("AWS_REGION", "us-east-1")

    logger.info(f"Initializing seeding for table '{table_name}' on region '{region_name}'...")

    db = boto3.resource("dynamodb", region_name=region_name, endpoint_url=endpoint_url)
    
    # 1. Check/Create Table (if running locally or in test container)
    try:
        table = db.Table(table_name)
        table.load()
        logger.info(f"Table '{table_name}' already exists.")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException" or "not found" in str(e).lower():
            logger.info(f"Table '{table_name}' not found. Attempting to create it locally...")
            try:
                table = db.create_table(
                    TableName=table_name,
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
                table.meta.client.get_waiter("table_exists").wait(TableName=table_name)
                logger.info(f"Created table '{table_name}' successfully.")
            except Exception as create_err:
                logger.error(f"Failed to create table: {create_err}")
                return
        else:
            logger.error(f"DynamoDB connection error: {e}")
            return

    # 2. Seed Mock Data using repository
    repo = DynamoDBRepository()

    # Seed Warehouses
    w1_id = "11111111-1111-1111-1111-111111111111"
    w2_id = "22222222-2222-2222-2222-222222222222"
    
    logger.info("Seeding warehouses...")
    repo.create_warehouse(w1_id, "Texas Drone Port (San Antonio)", "San Antonio, TX")
    repo.create_warehouse(w2_id, "New York Fulfillment Hub", "Brooklyn, NY")

    # Seed Drones
    d1_id = "33333333-3333-3333-3333-333333333333"
    d2_id = "44444444-4444-4444-4444-444444444444"
    d3_id = "55555555-5555-5555-5555-555555555555"

    logger.info("Seeding drones...")
    repo.create_drone(w1_id, d1_id, "DJI Mavic 3 Enterprise", "Active")
    repo.create_drone(w1_id, d2_id, "DJI Matrice 300 RTK", "Maintenance")
    repo.create_drone(w2_id, d3_id, "Skydio X2D Autonomous", "Active")

    logger.info("Seeding completed successfully!")
    logger.info(f"Warehouse 1: {w1_id}")
    logger.info(f"Warehouse 2: {w2_id}")
    logger.info(f"Drone 1 (Texas): {d1_id}")
    logger.info(f"Drone 2 (Texas): {d2_id}")
    logger.info(f"Drone 3 (New York): {d3_id}")


if __name__ == "__main__":
    init_and_seed()
