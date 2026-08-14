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

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

_MAGIC = {
    b"%PDF-": "application/pdf",
    b"PK\x03\x04": DOCX_MIME,
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
}

#: Filename suffixes this module recognises, per MIME type. The UI reads these
#: through ``/v1/upload-limits`` so it can never advertise a format the scanner
#: would go on to reject. Extending the allowed set means editing this map, not
#: a list somewhere in the frontend.
EXTENSIONS_BY_MIME: dict[str, tuple[str, ...]] = {
    "application/pdf": (".pdf",),
    DOCX_MIME: (".docx",),
    "application/msword": (".doc",),
    "image/jpeg": (".jpg", ".jpeg"),
    "image/png": (".png",),
    "text/plain": (".txt",),
    "text/markdown": (".md",),
}


def allowed_mime_types() -> list[str]:
    return sorted(get_settings().allowed_upload_mime)


def allowed_extensions() -> list[str]:
    """Every suffix an upload may carry, for the file picker's accept list."""
    permitted = get_settings().allowed_upload_mime
    return sorted(
        suffix
        for mime, suffixes in EXTENSIONS_BY_MIME.items()
        if mime in permitted
        for suffix in suffixes
    )


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
    # Longest suffix first, so ".docx" is never matched as ".doc".
    for suffix, mime in sorted(
        ((s, m) for m, suffixes in EXTENSIONS_BY_MIME.items() for s in suffixes),
        key=lambda pair: len(pair[0]),
        reverse=True,
    ):
        if lowered.endswith(suffix):
            return mime
    return "application/octet-stream"
