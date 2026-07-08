import base64
import hashlib
import json
import os
from typing import Dict, List, Optional, Tuple
import boto3
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key
from src.models.event import Event
from src.models.image import Image
from src.models.inspection import Inspection
from src.models.idempotency import IdempotencyRecord
from src.utils.logger import logger
from src.utils.response import (
    EntityNotFoundError,
    IdempotencyConflictError,
    OptimisticLockError,
    convert_decimals,
)


def encode_cursor(key_dict: Optional[dict]) -> str:
    """Encodes a DynamoDB LastEvaluatedKey dictionary into a base64 string."""
    if not key_dict:
        return ""
    cleaned_dict = convert_decimals(key_dict)
    json_str = json.dumps(cleaned_dict)
    return base64.b64encode(json_str.encode("utf-8")).decode("utf-8")


def decode_cursor(cursor_str: Optional[str]) -> Optional[dict]:
    """Decodes a base64 string into a DynamoDB ExclusiveStartKey dictionary."""
    if not cursor_str:
        return None
    try:
        json_bytes = base64.b64decode(cursor_str.encode("utf-8"))
        return json.loads(json_bytes.decode("utf-8"))
    except Exception as e:
        logger.warning(f"Failed to decode pagination cursor: {e}")
        raise ValueError("Invalid pagination token")


class DynamoDBRepository:
    def __init__(self, table_name: Optional[str] = None):
        self.table_name = table_name or os.environ.get("TABLE_NAME", "DroneInspectionTable")
        self.region_name = os.environ.get("AWS_REGION", "us-east-1")
        
        # Initialize DynamoDB resource configuration
        endpoint_url = os.environ.get("DYNAMODB_ENDPOINT_URL")
        self.db = boto3.resource("dynamodb", region_name=self.region_name, endpoint_url=endpoint_url)
        self.table = self.db.Table(self.table_name)

    def create_warehouse(self, warehouse_id: str, name: str, location: str, org_id: str = "DEFAULT-TENANT") -> dict:
        """Helper to seed warehouse records under organization tenant partitions."""
        item = {
            "PK": f"ORG#{org_id}#WAREHOUSE#{warehouse_id}",
            "SK": "METADATA",
            "EntityType": "Warehouse",
            "organization_id": org_id,
            "warehouse_id": warehouse_id,
            "name": name,
            "location": location,
            "created_at": "2026-07-08T00:00:00Z"
        }
        self.table.put_item(Item=item)
        return item

    def create_drone(self, warehouse_id: str, drone_id: str, model: str, status: str, org_id: str = "DEFAULT-TENANT") -> dict:
        """Helper to seed drone records under organization tenant partitions."""
        item = {
            "PK": f"ORG#{org_id}#WAREHOUSE#{warehouse_id}",
            "SK": f"DRONE#{drone_id}",
            "EntityType": "Drone",
            "organization_id": org_id,
            "warehouse_id": warehouse_id,
            "drone_id": drone_id,
            "model": model,
            "status": status,
            "created_at": "2026-07-08T00:00:00Z"
        }
        self.table.put_item(Item=item)
        return item

    def get_warehouse(self, warehouse_id: str, org_id: str = "DEFAULT-TENANT") -> Optional[dict]:
        """Fetches a warehouse metadata record."""
        try:
            response = self.table.get_item(
                Key={"PK": f"ORG#{org_id}#WAREHOUSE#{warehouse_id}", "SK": "METADATA"}
            )
            return response.get("Item")
        except ClientError as e:
            logger.error(f"Error fetching warehouse: {e}")
            raise

    def get_drone(self, warehouse_id: str, drone_id: str, org_id: str = "DEFAULT-TENANT") -> Optional[dict]:
        """Fetches a drone metadata record under a warehouse partition."""
        try:
            response = self.table.get_item(
                Key={"PK": f"ORG#{org_id}#WAREHOUSE#{warehouse_id}", "SK": f"DRONE#{drone_id}"}
            )
            return response.get("Item")
        except ClientError as e:
            logger.error(f"Error fetching drone: {e}")
            raise

    def check_and_lock_idempotency(self, key: str) -> Tuple[str, Optional[dict]]:
        """Attempts to acquire an idempotency lock for the given key."""
        pk = f"IDEMPOTENCY#{key}"
        sk = "RESULT"
        import time
        from src.utils.constants import IDEMPOTENCY_TTL_SECONDS
        ttl_value = int(time.time()) + IDEMPOTENCY_TTL_SECONDS
        
        try:
            self.table.put_item(
                Item={
                    "PK": pk,
                    "SK": sk,
                    "EntityType": "Idempotency",
                    "idempotency_key": key,
                    "status": "IN_PROGRESS",
                    "ttl": ttl_value
                },
                ConditionExpression="attribute_not_exists(PK)"
            )
            logger.info(f"Acquired idempotency lock for key: {key}")
            return "LOCKED", None
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                res = self.table.get_item(Key={"PK": pk, "SK": sk})
                item = res.get("Item")
                if not item:
                    return self.check_and_lock_idempotency(key)
                
                status = item.get("status")
                logger.info(f"Idempotency match found for key: {key}, status: {status}")
                if status == "COMPLETED":
                    response_json = item.get("response_json")
                    response_dict = json.loads(response_json) if response_json else {}
                    return "COMPLETED", response_dict
                else:
                    return "IN_PROGRESS", None
            else:
                logger.error(f"Failed idempotency operations: {e}")
                raise

    def update_idempotency_result(self, key: str, response_dict: dict):
        """Updates the idempotency lock with the final execution response."""
        pk = f"IDEMPOTENCY#{key}"
        sk = "RESULT"
        try:
            self.table.update_item(
                Key={"PK": pk, "SK": sk},
                UpdateExpression="SET #status = :completed, #res = :res",
                ExpressionAttributeNames={"#status": "status", "#res": "response_json"},
                ExpressionAttributeValues={
                    ":completed": "COMPLETED",
                    ":res": json.dumps(response_dict)
                }
            )
            logger.info(f"Updated idempotency result for key: {key}")
        except ClientError as e:
            logger.error(f"Failed to update idempotency key {key}: {e}")

    def create_inspection(self, inspection: Inspection) -> dict:
        """Saves an inspection record to DynamoDB and duplicates snapshot version 1."""
        org_id = inspection.organization_id
        # 1. Verify warehouse metadata exists
        warehouse = self.get_warehouse(inspection.warehouse_id, org_id)
        if not warehouse:
            raise EntityNotFoundError(f"Warehouse '{inspection.warehouse_id}' not found.")

        # 2. Verify drone exists
        drone = self.get_drone(inspection.warehouse_id, inspection.drone_id, org_id)
        if not drone:
            raise EntityNotFoundError(
                f"Drone '{inspection.drone_id}' does not exist inside Warehouse '{inspection.warehouse_id}'."
            )

        # 3. Write active inspection item
        item = {
            "PK": f"ORG#{org_id}#WAREHOUSE#{inspection.warehouse_id}",
            "SK": f"INSPECTION#{inspection.inspection_id}",
            "GSI1PK": f"DRONE#{inspection.drone_id}",
            "GSI1SK": f"INSPECTION#{inspection.inspection_id}",
            "EntityType": "Inspection",
            **inspection.model_dump()
        }
        
        try:
            self.table.put_item(Item=item)
            
            # Save history version snapshot for time-travel records (Version 1)
            history_item = {
                **item,
                "SK": f"INSPECTION#{inspection.inspection_id}#VERSION#1",
                "EntityType": "InspectionHistory"
            }
            self.table.put_item(Item=history_item)
            
            logger.info(f"Created inspection: {inspection.inspection_id}")
            return item
        except ClientError as e:
            logger.error(f"Error saving inspection: {e}")
            raise

    def get_inspection(self, warehouse_id: str, inspection_id: str, org_id: str = "DEFAULT-TENANT") -> Optional[dict]:
        """Retrieves an inspection by warehouse ID and inspection ID."""
        try:
            response = self.table.get_item(
                Key={
                    "PK": f"ORG#{org_id}#WAREHOUSE#{warehouse_id}",
                    "SK": f"INSPECTION#{inspection_id}"
                }
            )
            return response.get("Item")
        except ClientError as e:
            logger.error(f"Error fetching inspection: {e}")
            raise

    def get_inspection_by_id_only(self, inspection_id: str) -> Optional[dict]:
        """Finds an active inspection record when only inspection_id is available using InvertedIndex."""
        try:
            response = self.table.query(
                IndexName="InvertedIndex",
                KeyConditionExpression=Key("SK").eq(f"INSPECTION#{inspection_id}")
            )
            items = response.get("Items", [])
            return items[0] if items else None
        except ClientError as e:
            logger.error(f"Error finding inspection by SK: {e}")
            raise

    def get_inspection_version(self, inspection_id: str, version: int) -> Optional[dict]:
        """Retrieves a historical version snapshot of an inspection using InvertedIndex."""
        try:
            response = self.table.query(
                IndexName="InvertedIndex",
                KeyConditionExpression=Key("SK").eq(f"INSPECTION#{inspection_id}#VERSION#{version}")
            )
            items = response.get("Items", [])
            return items[0] if items else None
        except ClientError as e:
            logger.error(f"Error fetching historical version: {e}")
            raise

    def get_inspection_history_all_versions(self, inspection_id: str) -> List[dict]:
        """Fetches all historical snapshots of an inspection in chronological order."""
        insp = self.get_inspection_by_id_only(inspection_id)
        if not insp:
            return []
        org_id = insp.get("organization_id", "DEFAULT-TENANT")
        warehouse_id = insp.get("warehouse_id")
        
        try:
            res = self.table.query(
                KeyConditionExpression=Key("PK").eq(f"ORG#{org_id}#WAREHOUSE#{warehouse_id}") &
                                       Key("SK").begins_with(f"INSPECTION#{inspection_id}#VERSION#")
            )
            return res.get("Items", [])
        except ClientError as e:
            logger.error(f"Error fetching history versions: {e}")
            raise

    def update_inspection_status(
        self, warehouse_id: str, inspection_id: str, new_status: str, current_version: int, org_id: str = "DEFAULT-TENANT"
    ) -> dict:
        """Updates inspection status with optimistic locking and writes a snapshot version."""
        from src.models.base import current_utc_time
        pk = f"ORG#{org_id}#WAREHOUSE#{warehouse_id}"
        sk = f"INSPECTION#{inspection_id}"
        
        try:
            response = self.table.update_item(
                Key={"PK": pk, "SK": sk},
                UpdateExpression="SET #status = :new_status, version = version + :inc, updated_at = :now",
                ConditionExpression="version = :current_version",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":new_status": new_status,
                    ":inc": 1,
                    ":current_version": current_version,
                    ":now": current_utc_time()
                },
                ReturnValues="ALL_NEW"
            )
            updated_attrs = response.get("Attributes")
            logger.info(f"Updated inspection {inspection_id} status to {new_status}")

            # Save version history item for time travel
            new_version = updated_attrs.get("version")
            history_item = {
                **updated_attrs,
                "SK": f"INSPECTION#{inspection_id}#VERSION#{new_version}",
                "EntityType": "InspectionHistory"
            }
            self.table.put_item(Item=history_item)

            return updated_attrs
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                logger.warning(f"Optimistic locking failure updating inspection {inspection_id}")
                raise OptimisticLockError(
                    f"Conflict updating inspection '{inspection_id}'. Version has changed."
                )
            logger.error(f"Failed to update inspection status: {e}")
            raise

    def list_warehouse_inspections(
        self, warehouse_id: str, limit: int, last_evaluated_key: Optional[dict] = None, org_id: str = "DEFAULT-TENANT"
    ) -> Tuple[List[dict], Optional[dict]]:
        """Queries all inspections for a warehouse tenant partition with pagination."""
        query_kwargs = {
            "KeyConditionExpression": Key("PK").eq(f"ORG#{org_id}#WAREHOUSE#{warehouse_id}") & Key("SK").begins_with("INSPECTION#"),
            "Limit": limit
        }
        if last_evaluated_key:
            query_kwargs["ExclusiveStartKey"] = last_evaluated_key

        try:
            res = self.table.query(**query_kwargs)
            # Filter out version snapshots and history records from list result
            items = [it for it in res.get("Items", []) if "#VERSION#" not in it.get("SK", "")]
            return items, res.get("LastEvaluatedKey")
        except ClientError as e:
            logger.error(f"Failed listing warehouse inspections: {e}")
            raise

    def list_drone_inspections(
        self, drone_id: str, limit: int, last_evaluated_key: Optional[dict] = None
    ) -> Tuple[List[dict], Optional[dict]]:
        """Queries all inspections for a drone using GSI1 index with pagination."""
        query_kwargs = {
            "IndexName": "GSI1",
            "KeyConditionExpression": Key("GSI1PK").eq(f"DRONE#{drone_id}") & Key("GSI1SK").begins_with("INSPECTION#"),
            "Limit": limit
        }
        if last_evaluated_key:
            query_kwargs["ExclusiveStartKey"] = last_evaluated_key

        try:
            res = self.table.query(**query_kwargs)
            # Filter out version snapshots from list result
            items = [it for it in res.get("Items", []) if "#VERSION#" not in it.get("GSI1SK", "")]
            return items, res.get("LastEvaluatedKey")
        except ClientError as e:
            logger.error(f"Failed listing drone inspections: {e}")
            raise

    def save_image_upload(self, image: Image):
        """Saves a pending or uploaded image record."""
        item = {
            "PK": f"INSPECTION#{image.inspection_id}",
            "SK": f"IMAGE#{image.image_id}",
            "EntityType": "Image",
            **image.model_dump()
        }
        try:
            self.table.put_item(Item=item)
            logger.info(f"Registered image record: {image.image_id} for inspection {image.inspection_id}")
        except ClientError as e:
            logger.error(f"Failed saving image upload metadata: {e}")
            raise

    def get_image(self, inspection_id: str, image_id: str) -> Optional[dict]:
        """Fetches an image record."""
        try:
            res = self.table.get_item(
                Key={"PK": f"INSPECTION#{inspection_id}", "SK": f"IMAGE#{image_id}"}
            )
            return res.get("Item")
        except ClientError as e:
            logger.error(f"Error fetching image: {e}")
            raise

    def update_image_upload_complete(
        self, inspection_id: str, image_id: str, width: int, height: int, uploaded_at: str
    ) -> dict:
        """Marks image status as UPLOADED and deletes DynamoDB TTL."""
        try:
            response = self.table.update_item(
                Key={"PK": f"INSPECTION#{inspection_id}", "SK": f"IMAGE#{image_id}"},
                UpdateExpression="SET #status = :uploaded, width = :w, height = :h, uploaded_at = :at REMOVE #t",
                ExpressionAttributeNames={"#status": "status", "#t": "ttl"},
                ExpressionAttributeValues={
                    ":uploaded": "UPLOADED",
                    ":w": width,
                    ":h": height,
                    ":at": uploaded_at
                },
                ReturnValues="ALL_NEW"
            )
            logger.info(f"Marked image {image_id} as uploaded.")
            return response.get("Attributes")
        except ClientError as e:
            logger.error(f"Failed to update image complete state: {e}")
            raise

    def list_inspection_images(self, inspection_id: str) -> List[dict]:
        """Lists all images/uploads associated with an inspection."""
        try:
            res = self.table.query(
                KeyConditionExpression=Key("PK").eq(f"INSPECTION#{inspection_id}") & Key("SK").begins_with("IMAGE#")
            )
            return res.get("Items", [])
        except ClientError as e:
            logger.error(f"Failed listing inspection images: {e}")
            raise

    def create_event(self, event: Event):
        """Saves a timeline/audit event with SHA-256 chaining."""
        try:
            # Query the latest event for this inspection to chain hashes
            res = self.table.query(
                KeyConditionExpression=Key("PK").eq(f"INSPECTION#{event.inspection_id}") & Key("SK").begins_with("EVENT#"),
                ScanIndexForward=False,
                Limit=1
            )
            items = res.get("Items", [])
            if items:
                previous_hash = items[0].get("hash", "0" * 64)
            else:
                previous_hash = "0" * 64
                
            event.previous_hash = previous_hash
            
            # Compute SHA-256 hash of event fields
            et_str = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
            payload_str = json.dumps(convert_decimals(event.payload or {}), sort_keys=True)
            chain_string = f"{event.event_id}|{event.inspection_id}|{et_str}|{event.timestamp}|{payload_str}|{previous_hash}"
            event.hash = hashlib.sha256(chain_string.encode("utf-8")).hexdigest()
            
            item = {
                "PK": f"INSPECTION#{event.inspection_id}",
                "SK": f"EVENT#{event.timestamp}#{event.event_id}",
                "EntityType": "Event",
                **event.model_dump()
            }
            self.table.put_item(Item=item)
            logger.info(f"Recorded event {event.event_type} (Hash: {event.hash[:8]}) for inspection {event.inspection_id}")
        except Exception as e:
            logger.error(f"Failed saving event timeline item: {e}")
            raise

    def list_inspection_timeline(self, inspection_id: str) -> List[dict]:
        """Retrieves the history event log for an inspection sorted chronologically."""
        try:
            res = self.table.query(
                KeyConditionExpression=Key("PK").eq(f"INSPECTION#{inspection_id}") & Key("SK").begins_with("EVENT#")
            )
            return res.get("Items", [])
        except ClientError as e:
            logger.error(f"Failed listing timeline: {e}")
            raise
