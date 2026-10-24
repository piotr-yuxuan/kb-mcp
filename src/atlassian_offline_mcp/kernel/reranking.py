"""The bounds of one reranking request, named once for every context.

Standard library only, so that the settings' depth, the text that search scores and the
reranking adapter's checks all take them from here.
"""

from __future__ import annotations

# The most texts one request scores: the deepest reranking a search may ask for.
MOST_TEXTS = 64
# The longest text scored: a title and a heading of 150 characters each, a line each,
# then 1,200 characters of a section's body (011's piece, 019's 300-token window).
LONGEST_TEXT = 1_502
# The longest query scored: the bound that ``search`` and ``ask`` already put on one.
LONGEST_QUERY = 500
