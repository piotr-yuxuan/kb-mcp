"""When a document absent from its listing is believed gone, as the plan rules."""

from __future__ import annotations

from datetime import UTC, datetime

from atlassian_offline_mcp.domain.deletions import Answer, Tombstone, after_probes, too_many_gone

FIRST = datetime(2026, 11, 1, tzinfo=UTC)
LATER = datetime(2026, 11, 2, tzinfo=UTC)
PAGE = ("pages", "1001")
SPACE = "196613"


def stone(*, confirmed: bool = False) -> Tombstone:
    """Return the tombstone of the page, as the first run made it."""
    return Tombstone("pages", "1001", SPACE, FIRST, confirmed=confirmed)


def test_a_first_gone_answer_makes_a_tombstone_not_yet_confirmed() -> None:
    """One answer is not enough: a moment of trouble on the site would purge pages."""
    kept = after_probes({}, {PAGE: SPACE}, {PAGE: Answer.GONE}, FIRST)
    assert kept == {PAGE: stone()}


def test_a_second_gone_answer_confirms_it() -> None:
    """Absent and gone on a later run: the mirror can leave the page out."""
    kept = after_probes({PAGE: stone()}, {PAGE: SPACE}, {PAGE: Answer.GONE}, LATER)
    assert kept == {PAGE: stone(confirmed=True)}


def test_a_page_listed_again_loses_its_tombstone() -> None:
    """Back in the listing, even after confirmation: it is shown again."""
    assert after_probes({PAGE: stone(confirmed=True)}, {}, {}, LATER) == {}


def test_a_moved_or_present_page_loses_its_tombstone() -> None:
    """Found elsewhere, or still there: not gone."""
    for answer in (Answer.MOVED, Answer.PRESENT):
        assert after_probes({PAGE: stone()}, {PAGE: SPACE}, {PAGE: answer}, LATER) == {}


def test_a_page_not_probed_this_run_keeps_its_tombstone_as_it_was() -> None:
    """Probes are bounded: the page waits for a later run, neither confirmed nor dropped."""
    assert after_probes({PAGE: stone()}, {PAGE: SPACE}, {}, LATER) == {PAGE: stone()}


def test_many_gone_at_once_call_for_a_check_of_the_session() -> None:
    """More than 10, or more than 5% of the stored documents, is too many to believe."""
    gone = {("pages", str(n)): Answer.GONE for n in range(11)}
    assert too_many_gone(gone, 10_000)
    assert too_many_gone(dict(list(gone.items())[:6]), 100)
    assert not too_many_gone(dict(list(gone.items())[:5]), 100)
    assert not too_many_gone({PAGE: Answer.MOVED}, 1)
