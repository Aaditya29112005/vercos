from src.services.inspection_service import InspectionService
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

    query_params = event.get("queryStringParameters") or {}
    version_str = query_params.get("version")
    version = int(version_str) if version_str else None

    service = InspectionService()
    result = service.get_inspection(inspection_id=inspection_id, version=version)

    request_context = event.get("requestContext", {})
    request_id = request_context.get("requestId") or request_context.get("http", {}).get(
        "requestId", ""
    )

    return format_response(
        status_code=200,
        success=True,
        message="Inspection retrieved successfully",
        data=result,
        request_id=request_id,
    )
