"""When a document absent from its listing is believed gone, as the plan rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from atlassian_offline_mcp.domain.content import RefusedError
from atlassian_offline_mcp.domain.deletions import (
    Answer,
    Tombstone,
    after_probes,
    answer_of,
    probing_order,
    too_many_gone,
)

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


def test_a_moved_page_loses_its_tombstone_and_an_unsettled_one_waits_again() -> None:
    """Followed into a space that lists it: not gone. Found, but unlisted: pending again."""
    assert after_probes({PAGE: stone()}, {PAGE: SPACE}, {PAGE: Answer.MOVED}, LATER) == {}
    unsettled = after_probes({PAGE: stone()}, {PAGE: SPACE}, {PAGE: Answer.UNSETTLED}, LATER)
    assert unsettled == {PAGE: Tombstone("pages", "1001", SPACE)}


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


def test_a_second_answer_within_the_hour_does_not_confirm() -> None:
    """Two runs moments apart prove little: the tombstone waits."""
    soon = FIRST + timedelta(minutes=5)
    kept = after_probes({PAGE: stone()}, {PAGE: SPACE}, {PAGE: Answer.GONE}, soon)
    assert kept == {PAGE: stone()}


def test_a_trashed_or_out_of_scope_page_is_gone_and_one_listed_elsewhere_moved() -> None:
    """Trashed, or where the store never looks, is gone; moved once a kept listing names it."""
    kept = {SPACE, "300000"}
    assert answer_of(SPACE, "trashed", kept, named=True) is Answer.GONE
    assert answer_of("999999", "current", kept, named=False) is Answer.GONE
    assert answer_of("300000", "current", kept, named=True) is Answer.MOVED
    assert answer_of("300000", "current", kept, named=False) is Answer.UNSETTLED
    assert answer_of(SPACE, "archived", kept, named=False) is Answer.UNSETTLED


def test_a_confirmation_without_a_first_answer_of_gone_is_refused() -> None:
    """Confirmed means answered gone twice: a tombstone saying otherwise is damaged."""
    with pytest.raises(RefusedError, match="confirmed"):
        Tombstone("pages", "1001", SPACE, confirmed=True)


def test_pages_on_their_way_are_probed_first_and_confirmed_ones_not_at_all() -> None:
    """A cap on probes never starves a confirmation, nor is spent on settled pages."""
    absent = [("pages", "1"), ("pages", "2"), ("pages", "3"), ("pages", "4")]
    known = {
        ("pages", "3"): Tombstone("pages", "3", SPACE, FIRST),
        ("pages", "4"): Tombstone("pages", "4", SPACE, FIRST, confirmed=True),
    }
    assert probing_order(absent, known) == [("pages", "3"), ("pages", "1"), ("pages", "2")]


def test_an_absent_page_without_an_answer_waits_as_pending() -> None:
    """No answer this run (a failed probe, the cap, a silent site): it waits, not lost."""
    kept = after_probes({}, {PAGE: SPACE}, {}, FIRST)
    assert kept == {PAGE: Tombstone("pages", "1001", SPACE)}
    answered = after_probes(kept, {PAGE: SPACE}, {PAGE: Answer.GONE}, LATER)
    assert answered == {PAGE: Tombstone("pages", "1001", SPACE, LATER)}


def test_a_confirmed_page_absent_and_unprobed_stays_confirmed() -> None:
    """Confirmed pages are not probed again, and stay confirmed while absent."""
    assert after_probes({PAGE: stone(confirmed=True)}, {PAGE: SPACE}, {}, LATER) == {
        PAGE: stone(confirmed=True)
    }
