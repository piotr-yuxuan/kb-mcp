"""The bounds of reranking, named once for every context.

Standard library only, so that the settings' depth, the text that search scores, the
reranking adapter's checks and the reranker's check all take them from here.
"""

from __future__ import annotations

# The most texts one request scores: the deepest reranking a search may ask for.
MOST_TEXTS = 64
# The longest text scored: a title and a heading of 150 characters each, a line each,
# then 1,200 characters of a section's body (011's piece, 019's 300-token window).
LONGEST_TEXT = 1_502
# The longest query scored: the bound that ``search`` and ``ask`` already put on one.
LONGEST_QUERY = 500
# The depths that a reranking may have: from two documents, the fewest with an order to
# change, to the most that one request scores.
DEPTHS = range(2, MOST_TEXTS + 1)
# The user's bound on a search with reranking, at the 95th percentile on the user's machine
# ("Happy to wait 5s"), which plan 022's bar and the reranker's check read.
BOUND_S = 5.0
