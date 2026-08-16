"""The Secure AI Gateway boundary.

Every external model call this service makes goes out through
:class:`~app.gateway.client.SecureGatewayClient`. The gateway credential lives
in this process only: it is never sent to the browser, never persisted, never
logged, and never included in an audit record.
"""

from .client import ChatMessage, ChatReply, SecureGatewayClient, build_client
from .errors import (
    MAX_REQUEST_BYTES,
    GatewayAuthError,
    GatewayError,
    GatewayInvalidRequest,
    GatewayPolicyBlocked,
    GatewayRateLimited,
    GatewayRequestTooLarge,
    GatewayUnavailable,
)

__all__ = [
    "MAX_REQUEST_BYTES",
    "ChatMessage",
    "ChatReply",
    "GatewayAuthError",
    "GatewayError",
    "GatewayInvalidRequest",
    "GatewayPolicyBlocked",
    "GatewayRateLimited",
    "GatewayRequestTooLarge",
    "GatewayUnavailable",
    "SecureGatewayClient",
    "build_client",
]
