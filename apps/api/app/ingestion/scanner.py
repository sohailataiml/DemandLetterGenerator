"""Upload validation and malware screening.

The built-in checks are type/size validation plus an EICAR signature test. A
real deployment should point ``DLG_CLAMAV_HOST`` at a scanner and implement
:func:`_external_scan`; until then the gap is explicit rather than implied.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from ..config import get_settings

# The EICAR standard anti-virus test string, split so this file itself is not
# flagged by scanners that inspect source.
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"

_MAGIC = {
    b"%PDF-": "application/pdf",
    b"PK\x03\x04": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
}


class UnsafeFileError(ValueError):
    """The upload failed validation or screening and was not stored."""


@dataclass(frozen=True)
class ScanResult:
    mime_type: str
    size_bytes: int
    detected_magic: str | None


def _external_scan(data: bytes) -> None:
    """Hook for a real AV scanner (e.g. ClamAV via clamd). No-op by default."""
    if os.environ.get("DLG_CLAMAV_HOST"):  # pragma: no cover - deployment specific
        raise UnsafeFileError(
            "DLG_CLAMAV_HOST is set but no scanner client is wired up; "
            "implement _external_scan before accepting uploads in this environment"
        )


def scan(filename: str, data: bytes, declared_mime: str | None = None) -> ScanResult:
    settings = get_settings()

    if not data:
        raise UnsafeFileError("empty upload")
    if len(data) > settings.max_upload_bytes:
        raise UnsafeFileError(
            f"file is {len(data)} bytes; limit is {settings.max_upload_bytes} bytes"
        )
    if EICAR in data:
        raise UnsafeFileError("malware signature detected (EICAR test file)")

    detected = None
    for magic, mime in _MAGIC.items():
        if data.startswith(magic):
            detected = mime
            break

    mime = detected or declared_mime or _guess_from_name(filename)
    if mime not in settings.allowed_upload_mime:
        raise UnsafeFileError(
            f"unsupported content type {mime!r}; allowed: {sorted(settings.allowed_upload_mime)}"
        )

    # A .pdf that is really a zip is a red flag worth rejecting, not repairing.
    if detected and declared_mime and detected != declared_mime:
        if not (
            detected.startswith("application/vnd.openxml")
            and declared_mime.startswith("application/vnd.openxml")
        ):
            raise UnsafeFileError(
                f"content does not match declared type: bytes look like {detected!r}, "
                f"upload declared {declared_mime!r}"
            )

    _external_scan(data)
    return ScanResult(mime_type=mime, size_bytes=len(data), detected_magic=detected)


def _guess_from_name(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".pdf"):
        return "application/pdf"
    if lowered.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if lowered.endswith(".doc"):
        return "application/msword"
    if lowered.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".md"):
        return "text/markdown"
    if lowered.endswith(".txt"):
        return "text/plain"
    return "application/octet-stream"
