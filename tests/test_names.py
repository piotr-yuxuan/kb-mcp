"""Confluence's and Jira's names, spelt once, mean the same everywhere: plan 052.

``sources.atlassian.fetch.domain.names`` names the sources and their resource types, which
the declarations, the fetch and the prepare read. Coverage, which cannot import a
declaration, decides by a target's source whether its documents are found by update time:
it decides so where that source's declaration reads its resource types by a search.
"""

from __future__ import annotations

from kb_mcp.sources.atlassian.declared import CONFLUENCE, JIRA
from kb_mcp.sources.atlassian.fetch.domain.coverage import Target

# A key that each source's targets take.
KEYS = {CONFLUENCE.name: "MFS", JIRA.name: "PRB"}


def test_a_target_is_searched_by_time_where_its_source_reads_its_resource_types_so() -> None:
    """A project, whose issues Jira's declaration reads ``searched``; never a space."""
    assert {
        source.name: Target(source=source.name, key=KEYS[source.name]).searched_by_time
        for source in (CONFLUENCE, JIRA)
    } == {
        source.name: all(each.read == "searched" for each in source.resource_types)
        for source in (CONFLUENCE, JIRA)
    }
