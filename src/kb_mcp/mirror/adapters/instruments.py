"""The instruments of the documents that a run builds, which every source's preparer records.

``prepare`` records them for each source's documents, the work log's by kind, as
``docs/reference/telemetry/prepare.md`` lists them.
"""

from __future__ import annotations

from opentelemetry import metrics

METER = metrics.get_meter(__name__)
# The documents whose file a run built, or failed to; how long each took to build, pandoc
# writing its Markdown included. A span each would make a run's trace too large.
DOCUMENTS = METER.create_counter(
    "kb_mcp.prepare.documents", unit="{document}", description="Documents built, by outcome"
)
CONVERSION_DURATION = METER.create_histogram(
    "kb_mcp.prepare.conversion.duration", unit="s", description="How long a document's file took"
)
