import functools
import json
from decimal import Decimal
from pydantic import ValidationError
from aws_lambda_powertools.metrics import MetricUnit
from src.utils.logger import logger, metrics


def convert_decimals(obj):
    """Recursively converts Decimal objects to int or float for JSON serialization."""
    if isinstance(obj, list):
        return [convert_decimals(item) for item in obj]
    elif isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, Decimal):
        if obj % 1 == 0:
            return int(obj)
        return float(obj)
    return obj


class AppError(Exception):
    """Base application exception."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class EntityNotFoundError(AppError):
    """Raised when a warehouse, drone, inspection, or image is not found."""

    def __init__(self, message: str):
        super().__init__(message, 404)


class IdempotencyConflictError(AppError):
    """Raised when an idempotency key is reused but with a different payload."""

    def __init__(self, message: str):
        super().__init__(message, 409)


class OptimisticLockError(AppError):
    """Raised when version check fails on an update."""

    def __init__(self, message: str):
        super().__init__(message, 409)


def format_response(
    status_code: int, success: bool, message: str, data: dict = None, request_id: str = ""
) -> dict:
    """Formats standard Lambda proxy integration response."""
    cleaned_data = convert_decimals(data or {})
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token,Idempotency-Key",
            "Access-Control-Allow-Methods": "OPTIONS,POST,GET",
        },
        "body": json.dumps(
            {
                "success": success,
                "message": message,
                "data": cleaned_data,
                "requestId": request_id,
            }
        ),
    }


def handle_errors(func):
    """Decorator to handle errors globally in Lambda handlers."""

    @functools.wraps(func)
    def wrapper(event, context):
        request_id = ""
        if isinstance(event, dict):
            request_context = event.get("requestContext", {})
            # Look for requestId in either HTTP API or REST API payloads
            request_id = request_context.get("requestId") or request_context.get("http", {}).get(
                "requestId", ""
            )

        logger.set_correlation_id(request_id)

        try:
            return func(event, context)
        except ValidationError as e:
            logger.warning(f"Validation error: {e.errors()}")
            try:
                metrics.add_metric(name="Errors", unit=MetricUnit.Count, value=1)
            except Exception:
                pass
            errors = [
                {"field": ".".join(map(str, err["loc"])), "message": err["msg"]}
                for err in e.errors()
            ]
            return format_response(
                status_code=400,
                success=False,
                message="Input validation failed",
                data={"errors": errors},
                request_id=request_id,
            )
        except AppError as e:
            logger.warning(f"Application error: {e.message} (status: {e.status_code})")
            try:
                metrics.add_metric(name="Errors", unit=MetricUnit.Count, value=1)
            except Exception:
                pass
            return format_response(
                status_code=e.status_code,
                success=False,
                message=e.message,
                request_id=request_id,
            )
        except ValueError as e:
            logger.warning(f"Value error: {str(e)}")
            try:
                metrics.add_metric(name="Errors", unit=MetricUnit.Count, value=1)
            except Exception:
                pass
            return format_response(
                status_code=400, success=False, message=str(e), request_id=request_id
            )
        except Exception as e:
            logger.exception(f"Unhandled exception caught in middleware: {str(e)}")
            try:
                metrics.add_metric(name="Errors", unit=MetricUnit.Count, value=1)
            except Exception:
                pass
            return format_response(
                status_code=500, success=False, message="Internal server error", request_id=request_id
            )

    return wrapper
