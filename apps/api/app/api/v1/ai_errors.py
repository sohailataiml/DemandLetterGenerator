"""Turning an AI-boundary failure into an HTTP answer the reviewer can act on.

One rule shapes all of this: **the message must tell the attorney what happened
to their document**, and the answer is always the same — nothing. A failed
generation or revision writes nothing, so every message here says so explicitly
rather than leaving the reviewer to wonder whether half a section changed.

The status codes are this service's own. A gateway 401 is not relayed as 401:
the attorney is authenticated here, and it is our credential to the gateway that
failed. Telling their browser it is unauthenticated would be both false and
disruptive.
"""

from __future__ import annotations

from typing import Protocol

from fastapi import HTTPException


class BoundaryFailure(Protocol):
    """Shared shape of ``ProviderError``, ``RevisionError`` and friends."""

    code: str | None
    retry_after: float | None
    request_id: str | None
    http_status: int


#: What each status means for the document, in the reviewer's terms.
# Plain integers rather than starlette constants: the names for 413 and 422
# were renamed upstream, and a status code is not the thing worth abstracting.
_ADVICE = {
    429: (
        "The secure AI gateway is rate limiting this workspace. "
        "Wait a moment and try again; no {action} was applied."
    ),
    413: (
        "Generation context is too large for the secure AI gateway. "
        "Reduce the section context or use a narrower evidence set. "
        "No demand section was modified."
    ),
    422: (
        "The secure AI gateway's privacy policy declined this content, "
        "so no {action} was applied."
    ),
}

_DEFAULT = "{action} failed at the secure AI gateway; no changes were applied."


def provider_failure(exc: Exception, *, action: str) -> HTTPException:
    """Build the HTTPException for a drafting or revision failure.

    ``action`` is the verb used in the message ("drafting", "revision"), so the
    reviewer reads about the thing they asked for.
    """
    http_status = getattr(exc, "http_status", 502)
    template = _ADVICE.get(http_status, _DEFAULT)
    message = template.format(action=action)

    detail: dict[str, object] = {"message": f"{message} ({exc})"}
    code = getattr(exc, "code", None)
    if code:
        detail["gateway_error_code"] = code
    request_id = getattr(exc, "request_id", None)
    if request_id:
        # The gateway's own request id, so an operator can find the call in the
        # gateway's audit log. It identifies a request, not its content.
        detail["gateway_request_id"] = request_id

    headers: dict[str, str] | None = None
    retry_after = getattr(exc, "retry_after", None)
    if retry_after:
        headers = {"Retry-After": str(int(retry_after))}

    return HTTPException(status_code=http_status, detail=detail, headers=headers)
