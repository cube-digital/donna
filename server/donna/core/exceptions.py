from enum import IntEnum
from typing import Any

from rest_framework import status as drf_status
from rest_framework.exceptions import APIException


# Narrio error codes
class ErrorCode(IntEnum):
    HUBSPOT_TOKEN_EXPIRED = 1001


class NarrioAPIException(APIException):
    """ Base exception for all Narrio-specific API errors. """

    error_code: int | None = None

    def __init__(
        self,
        detail: Any = None,
        error_code: int | None = None,
    ) -> None:
        if error_code is not None:
            self.error_code = error_code
        super().__init__(detail=detail)


class HubSpotTokenExpiredError(NarrioAPIException):
    status_code = drf_status.HTTP_403_FORBIDDEN
    default_detail = (
        "Your HubSpot connection has expired. "
        "Please reconnect your HubSpot account to continue."
    )
    error_code = ErrorCode.HUBSPOT_TOKEN_EXPIRED


class HTTPException(APIException):
    """HTTP exception compatible with Django REST Framework."""

    status_code = 500
    default_detail = "A server error occurred."
    default_code = "error"

    def __init__(
        self,
        status_code: int = 500,
        error: str | None = None,
        detail: Any = None,
        headers: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.error = error
        self.headers = headers or {}
        super().__init__(detail=detail)


class NotFoundException(HTTPException):
    """404 Not Found."""

    status_code = drf_status.HTTP_404_NOT_FOUND
    default_detail = "Not Found"

    def __init__(
        self,
        detail: Any = None,
        headers: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            status_code=drf_status.HTTP_404_NOT_FOUND,
            error="Not Found",
            detail=detail,
            headers=headers,
        )


class BadRequestException(HTTPException):
    """400 Bad Request."""

    status_code = drf_status.HTTP_400_BAD_REQUEST
    default_detail = "Bad Request"

    def __init__(
        self,
        detail: Any = None,
        headers: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            status_code=drf_status.HTTP_400_BAD_REQUEST,
            error="Bad Request",
            detail=detail,
            headers=headers,
        )


class PaymentRequiredException(HTTPException):
    """402 Payment Required — feature is locked until checkout is completed."""

    status_code = 402
    default_detail = "Payment required."

    def __init__(self, checkout_url: str, charge_id: str) -> None:
        self.checkout_url = checkout_url
        self.charge_id = charge_id
        super().__init__(
            status_code=402,
            error="Payment Required",
            detail={
                "message": "Payment required to access this feature.",
                "checkout_url": checkout_url,
                "charge_id": charge_id,
            },
        )
