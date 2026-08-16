"""Failures at the privacy boundary, classified by what a caller should do.

The Secure AI Gateway returns a stable machine-readable ``code`` in an
``{"error": {...}}`` envelope. This module turns that envelope into exception
types the rest of the application can act on **without knowing any HTTP**, and
records two decisions per class that must never be made ad hoc at a call site:

``retryable``    whether re-sending could plausibly succeed. Authentication,
                 authorization, policy blocks, request-shape errors and
                 oversized bodies are permanent for this request; retrying them
                 wastes a rate-limit budget and, for a policy block, argues with
                 a decision that was deliberate.
``http_status``  what *this* service should return to its own browser client.
                 Notably a gateway 401/403 is **not** relayed as 401/403: the
                 attorney is authenticated with us, our credential to the
                 gateway is the thing that failed, and telling the browser it is
                 unauthenticated would be a lie that logs them out.

Nothing here ever carries the API key, a prompt, or a detected value.
"""

from __future__ import annotations

from typing import Any

#: The gateway's ordinary request-body cap (``MAX_REQUEST_BYTES``). Checked
#: locally before sending so an oversized prompt fails as a domain error
#: instead of burning a round trip and a rate-limit slot.
MAX_REQUEST_BYTES = 256 * 1024


class GatewayError(RuntimeError):
    """Base class for every Secure AI Gateway failure."""

    #: What this service should answer its own caller with.
    http_status: int = 502
    #: Whether a second attempt could plausibly succeed.
    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status: int | None = None,
        request_id: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.request_id = request_id
        self.retry_after = retry_after

    def as_audit_payload(self) -> dict[str, Any]:
        """Safe fields only: a code, a status, and the gateway's request id."""
        return {
            "gateway_error_code": self.code,
            "gateway_status": self.status,
            "gateway_request_id": self.request_id,
        }


class GatewayAuthError(GatewayError):
    """Our credential was missing, rejected, or not permitted to do this.

    Reported to the browser as a bad gateway: it is an operator problem with
    this service's configuration, not a problem with the attorney's session.
    """

    http_status = 502
    retryable = False


class GatewayInvalidRequest(GatewayError):
    """The gateway rejected the request shape, or the policy could not be found."""

    http_status = 502
    retryable = False


class GatewayPolicyBlocked(GatewayError):
    """The privacy policy refused this content. A deliberate decision, not a fault.

    Surfaced to the reviewer as 422 so the UI can say the gateway declined the
    material rather than implying the service is broken.
    """

    http_status = 422
    retryable = False


class GatewayRequestTooLarge(GatewayError):
    """The request body exceeds the gateway's ordinary-body limit."""

    http_status = 413
    retryable = False


class GatewayRateLimited(GatewayError):
    """The authenticated principal is over its rate limit.

    Never retried automatically. The limit is per principal, so a client-side
    retry loop would spend the same budget it is waiting on, and a duplicate
    generation costs a real upstream call.
    """

    http_status = 429
    retryable = False


class GatewayUnavailable(GatewayError):
    """The gateway, one of its dependencies, or the upstream provider failed."""

    http_status = 502
    retryable = True


#: Gateway ``ErrorCode`` values that mean "the privacy policy said no", as
#: opposed to "the request was malformed" — both arrive as HTTP 422.
_POLICY_BLOCK_CODES = frozenset({"POLICY_VIOLATION", "ENTITY_LIMIT_EXCEEDED"})

#: Dependency failures the gateway reports as 503. Transient by nature.
_DEPENDENCY_CODES = frozenset(
    {
        "PRIVACY_DETECTOR_UNAVAILABLE",
        "VAULT_UNAVAILABLE",
        "VAULT_ENCRYPTION_FAILED",
        "AUDIT_UNAVAILABLE",
    }
)


def classify(
    *, status: int, code: str | None, message: str, request_id: str | None, retry_after: float | None
) -> GatewayError:
    """Turn one gateway error response into the exception that describes it.

    Classification is driven by ``code`` where the code distinguishes cases the
    status alone cannot — 422 covers both a malformed request and a deliberate
    policy block, and those two must never be conflated.
    """
    detail = f"{code}: {message}" if code else message

    if status in (401, 403):
        return GatewayAuthError(detail, code=code, status=status, request_id=request_id)
    if status == 413 or code == "REQUEST_TOO_LARGE":
        return GatewayRequestTooLarge(detail, code=code, status=status, request_id=request_id)
    if status == 429 or code == "RATE_LIMIT_EXCEEDED":
        return GatewayRateLimited(
            detail, code=code, status=status, request_id=request_id, retry_after=retry_after
        )
    if code in _POLICY_BLOCK_CODES:
        return GatewayPolicyBlocked(detail, code=code, status=status, request_id=request_id)
    if status in (400, 409, 422):
        return GatewayInvalidRequest(detail, code=code, status=status, request_id=request_id)
    if status >= 500 or code in _DEPENDENCY_CODES:
        return GatewayUnavailable(detail, code=code, status=status, request_id=request_id)
    return GatewayError(detail, code=code, status=status, request_id=request_id)
