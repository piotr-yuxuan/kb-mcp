"""The mapping of plan 002's golden keys to refs that a mirror holds."""

from __future__ import annotations

import pytest

from spikes.golden_refs import UnmappedError, refs

QUESTION = {
    "id": "q001",
    "question": "How do I roll back?",
    "overlap": "paraphrase",
    "lang": "en",
    "expected": ["payments/payout-gateway-rollback", "ENG-74"],
    "partial": ["jira/dark-mode-dashboard"],
    "evidence": {"payments/payout-gateway-rollback": "Pause, drain, then roll back."},
}
NAMES = {
    "payments/payout-gateway-rollback": "Payout gateway rollback",
    "jira/dark-mode-dashboard": "Dark mode for the dashboard",
}
FOUND = {"Payout gateway rollback": "4001", "Dark mode for the dashboard": "PRB-3"}


def test_pages_by_title_ideas_by_summary_tickets_as_they_are() -> None:
    """Each key becomes the ref of the mirrored document of its name; groups are carried."""
    [question] = refs([QUESTION], NAMES, FOUND)
    assert question["expected"] == ["4001", "ENG-74"]
    assert question["partial"] == ["PRB-3"]
    assert question["groups"] == ["paraphrase", "en"]
    assert question["evidence"] == {"4001": "Pause, drain, then roll back."}


def test_a_key_the_mirror_lacks_is_refused_by_name() -> None:
    """A page not mirrored, or a key of no corpus file: nothing is written."""
    with pytest.raises(UnmappedError, match="payments/payout-gateway-rollback"):
        refs([QUESTION], NAMES, {"Dark mode for the dashboard": "PRB-3"})
    with pytest.raises(UnmappedError, match="jira/dark-mode-dashboard"):
        refs([QUESTION], {"payments/payout-gateway-rollback": "Payout gateway rollback"}, FOUND)
