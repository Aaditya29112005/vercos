import os
import sys

import boto3
import pytest
from moto import mock_aws

# Append src folder to sys path for imports to resolve properly in pytest run
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(scope="function")
def aws_env():
    """Sets up mock environment variables for test execution."""
    os.environ["TABLE_NAME"] = "DroneInspectionTable"
    os.environ["BUCKET_NAME"] = "drone-inspection-bucket"
    os.environ["AWS_REGION"] = "us-east-1"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    os.environ["AWS_ACCESS_KEY_ID"] = "mock_key"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "mock_secret"
    os.environ["AWS_SECURITY_TOKEN"] = "mock_security"
    os.environ["AWS_SESSION_TOKEN"] = "mock_session"


@pytest.fixture(scope="function")
def mock_db(aws_env):
    """Provides a mocked DynamoDB single-table schema matching SAM."""
    with mock_aws():
        db = boto3.resource("dynamodb", region_name="us-east-1")
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
        yield table


@pytest.fixture(scope="function")
def mock_s3_bucket(aws_env):
    """Provides a mocked S3 bucket matching SAM specifications."""
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="drone-inspection-bucket")
        yield s3

