import os
from typing import Optional

import boto3
from botocore.config import Config

from src.utils.logger import logger


def build_s3_key(
    warehouse_id: str, inspection_id: str, image_id: str, content_type: str, org_id: str = "DEFAULT-TENANT"
) -> str:
    """Constructs a clean tenant-isolated path inside the S3 bucket."""
    ext = "jpg"
    ct_lower = content_type.lower()
    if "png" in ct_lower:
        ext = "png"
    elif "webp" in ct_lower:
        ext = "webp"

    return f"tenants/{org_id}/warehouses/{warehouse_id}/inspections/{inspection_id}/images/{image_id}.{ext}"


class S3Repository:
    def __init__(self, bucket_name: Optional[str] = None):
        self.bucket_name = bucket_name or os.environ.get("BUCKET_NAME", "drone-inspection-bucket")
        self.region_name = os.environ.get("AWS_REGION", "us-east-1")

        # S3 endpoint_url configuration for mock environments
        endpoint_url = os.environ.get("S3_ENDPOINT_URL")

        # Pre-signed URLs require SigV4
        s3_config = Config(signature_version="s3v4")
        self.s3_client = boto3.client(
            "s3",
            region_name=self.region_name,
            config=s3_config,
            endpoint_url=endpoint_url
        )

    def generate_upload_url(self, key: str, expires_in: int, content_type: str) -> str:
        """Generates a pre-signed S3 URL for PUT operations."""
        try:
            url = self.s3_client.generate_presigned_url(
                ClientMethod="put_object",
                Params={
                    "Bucket": self.bucket_name,
                    "Key": key,
                    "ContentType": content_type
                },
                ExpiresIn=expires_in
            )
            logger.info(f"Generated pre-signed PUT URL for key: {key}")
            return url
        except Exception as e:
            logger.error(f"Failed to generate pre-signed URL: {e}")
            raise
