"""Which attached files a download keeps: what the mirror can show, within the cap."""

from __future__ import annotations

import pytest

from kb_mcp.sources.atlassian.fetch.domain.content import Attachment
from kb_mcp.sources.atlassian.fetch.domain.files import skip_reason

CAP = 50 * 1024 * 1024


def attachment(media_type: str, size: int = 1000) -> Attachment:
    """Return an attachment of a media type and size."""
    return Attachment(
        id="att1", filename="file", media_type=media_type, size=size, download="/wiki/download/att1"
    )


@pytest.mark.parametrize(
    "media_type", ["image/png", "image/svg+xml", "application/pdf", "text/plain", "IMAGE/JPEG"]
)
def test_images_and_documents_within_the_cap_are_kept(media_type: str) -> None:
    """Pictures and documents are downloaded."""
    assert skip_reason(attachment(media_type), CAP) is None


@pytest.mark.parametrize(
    "media_type", ["video/mp4", "audio/mpeg", "application/zip", "application/x-7z-compressed"]
)
def test_video_audio_and_archives_keep_their_metadata_only(media_type: str) -> None:
    """The mirror can neither show nor search them."""
    assert skip_reason(attachment(media_type), CAP) == "media type not kept"


def test_a_file_over_the_cap_is_not_downloaded() -> None:
    """The cap is inclusive: one byte more is over it."""
    assert skip_reason(attachment("image/png", CAP), CAP) is None
    assert skip_reason(attachment("image/png", CAP + 1), CAP) == "over the size cap"
