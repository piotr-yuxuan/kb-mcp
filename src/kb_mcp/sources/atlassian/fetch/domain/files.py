"""Which attached files a download keeps, and which keep their metadata only."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kb_mcp.sources.atlassian.fetch.domain.content import Attachment

# Media that the mirror cannot show or search: kept as metadata only.
SKIPPED_PREFIXES = ("video/", "audio/")
ARCHIVES = frozenset(
    {
        "application/gzip",
        "application/vnd.rar",
        "application/x-7z-compressed",
        "application/x-rar-compressed",
        "application/x-tar",
        "application/zip",
    }
)


def skip_reason(attachment: Attachment, max_bytes: int) -> str | None:
    """Return why an attachment's file is not downloaded, or None when it is."""
    media_type = attachment.media_type.lower()
    if media_type.startswith(SKIPPED_PREFIXES) or media_type in ARCHIVES:
        return "media type not kept"
    if attachment.size > max_bytes:
        return "over the size cap"
    return None
