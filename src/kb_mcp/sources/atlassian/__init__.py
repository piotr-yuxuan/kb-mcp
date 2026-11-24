"""Confluence and Jira Cloud: their fetch into the raw store, and their documents from it.

What its declaration, its fetch and its settings share, light, as the declaration is.
"""

from __future__ import annotations

import re

# A Confluence space key; a personal space's key begins with a tilde.
SPACE_KEY = re.compile(r"~?[A-Za-z0-9]+")
PROJECT_KEY = re.compile(r"[A-Z][A-Z0-9_]+")
