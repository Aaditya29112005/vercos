import base64
import json

from src.models.image import GenerateUploadURLInput
from src.services.upload_service import UploadService
from src.utils.response import format_response, handle_errors


from src.utils.logger import logger, tracer, metrics


@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start=True)
@logger.inject_lambda_context(clear_state=True)
@handle_errors
def lambda_handler(event, context):
    path_params = event.get("pathParameters") or {}
    inspection_id = path_params.get("id") or path_params.get("inspection_id")
    if not inspection_id:
        raise ValueError("Inspection ID path parameter 'id' is required")

    body_str = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        body_str = base64.b64decode(body_str).decode("utf-8")

    body = json.loads(body_str)
    validated_input = GenerateUploadURLInput(**body)

    service = UploadService()
    result = service.generate_upload_url(
        inspection_id=inspection_id,
        file_size=validated_input.file_size,
        content_type=validated_input.content_type,
        checksum=validated_input.checksum,
    )

    request_context = event.get("requestContext", {})
    request_id = request_context.get("requestId") or request_context.get("http", {}).get(
        "requestId", ""
    )

    return format_response(
        status_code=200,
        success=True,
        message="S3 pre-signed upload URL generated successfully",
        data=result,
        request_id=request_id,
    )
