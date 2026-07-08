from src.services.inspection_service import InspectionService
from src.utils.response import format_response, handle_errors


from src.utils.logger import logger, tracer, metrics


@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start=True)
@logger.inject_lambda_context(clear_state=True)
@handle_errors
def lambda_handler(event, context):
    path_params = event.get("pathParameters") or {}
    drone_id = path_params.get("id") or path_params.get("drone_id")
    if not drone_id:
        raise ValueError("Drone ID path parameter 'id' is required")

    query_params = event.get("queryStringParameters") or {}
    limit_str = query_params.get("limit") or "10"
    try:
        limit = int(limit_str)
    except ValueError:
        raise ValueError("Query parameter 'limit' must be an integer")

    cursor = query_params.get("cursor")

    service = InspectionService()
    result = service.list_drone_inspections(
        drone_id=drone_id, limit=limit, cursor_str=cursor
    )

    request_context = event.get("requestContext", {})
    request_id = request_context.get("requestId") or request_context.get("http", {}).get(
        "requestId", ""
    )

    return format_response(
        status_code=200,
        success=True,
        message="Drone inspections retrieved successfully",
        data=result,
        request_id=request_id,
    )
