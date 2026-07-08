import base64
import json
from src.models.inspection import CreateInspectionInput
from src.services.inspection_service import InspectionService
from src.utils.response import format_response, handle_errors


from src.utils.logger import logger, tracer, metrics


@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start=True)
@logger.inject_lambda_context(clear_state=True)
@handle_errors
def lambda_handler(event, context):
    body_str = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        body_str = base64.b64decode(body_str).decode("utf-8")
        
    body = json.loads(body_str)
    
    headers = event.get("headers") or {}
    idempotency_key = None
    for k, v in headers.items():
        if k.lower() == "idempotency-key":
            idempotency_key = v
            break

    # Pydantic validation (validates warehouse_id, drone_id, and optional organization_id)
    validated_input = CreateInspectionInput(**body)

    service = InspectionService()
    result = service.create_inspection(
        warehouse_id=validated_input.warehouse_id,
        drone_id=validated_input.drone_id,
        idempotency_key=idempotency_key,
        org_id=validated_input.organization_id
    )

    request_context = event.get("requestContext", {})
    request_id = request_context.get("requestId") or request_context.get("http", {}).get(
        "requestId", ""
    )

    return format_response(
        status_code=201,
        success=True,
        message="Inspection created successfully",
        data=result,
        request_id=request_id,
    )
