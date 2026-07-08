from src.services.inspection_service import InspectionService
from src.utils.response import format_response, handle_errors


@handle_errors
def lambda_handler(event, context):
    path_params = event.get("pathParameters") or {}
    inspection_id = path_params.get("id") or path_params.get("inspection_id")
    if not inspection_id:
        raise ValueError("Inspection ID path parameter 'id' is required")

    service = InspectionService()
    result = service.get_timeline(inspection_id=inspection_id)

    request_context = event.get("requestContext", {})
    request_id = request_context.get("requestId") or request_context.get("http", {}).get(
        "requestId", ""
    )

    return format_response(
        status_code=200,
        success=True,
        message="Inspection event timeline retrieved successfully",
        data={"timeline": result},
        request_id=request_id,
    )
