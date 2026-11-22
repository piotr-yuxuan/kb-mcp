# Differences

Where the code differs from a definition of [the concepts](concepts.md), one section per
difference, named by its entries. The definitions are timeless: they say what the
program is, and each section here says what the code does instead. Its class says what
closes it:

- A difference is **a defect of the code** when the definition holds: a plan fixes the
  code.
- It is **a defect of the definition** when the code holds: a plan that declares the
  change rewrites the definition.
- It is **an aspiration** when the definition says what the program is meant to become:
  a plan brings the code to it.
- It is **an intended gap** when the code departs from the definition on purpose, for
  the reason given: it stays so until a plan says otherwise.

## ranking: the section by words

An intended gap. A [ranking](concepts.md#ranking) names each document's section: for a
document that meaning placed, that of its best chunk, else its best section by words.
[`Ranking`](../../src/kb_mcp/mcp/app/tools.py) holds the chunk that matched, but not the
section by words: it is found when a page of the answer or the reranker reads it
([`snippet_of`](../../src/kb_mcp/mcp/app/tools.py),
[`place_of`](../../src/kb_mcp/mcp/app/tools.py)), since finding it for every document
ranked would cost a query of the words per document.

## connector and scope: origins without a connector

An aspiration. The [connector](concepts.md#connector) and [scope](concepts.md#scope)
entries name a repository, git, Notion and Google Drive as kinds of origin, as they name
Confluence, Jira and the work log. Connectors read only those three, in
[`sources/atlassian/`](../../src/kb_mcp/sources/atlassian/) and
[`sources/worklog/`](../../src/kb_mcp/sources/worklog/).
