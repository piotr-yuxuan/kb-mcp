"""What ``docs/reference/telemetry/`` says each command records, and what runs of it record.

Each page of the folder but ``README.md`` is a command's, named after it. Its tables of
events, spans and instruments, under the headings ``Events``, ``Spans`` and
``Instruments``, name each in their first column, in backticks; the README's, what every
command records. ``Emitted`` gathers what runs record: in this process, from the root
logger and the SDK's providers over in-memory exporters (``gathering``); in a fresh
interpreter, from the run's log file and the scripted collector (``collected``).
``undocumented`` compares what runs of a command recorded with its page and the README.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, override

from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.metrics.export import Gauge, Histogram, Sum
from opentelemetry.trace import get_current_span

from atlassian_offline_mcp.observability.adapters.telemetry import Exported
from tests.collector import attributes, plain

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from tests.collector import Collector
    from tests.conftest import InMemory

PAGES = Path(__file__).parents[1] / "docs" / "reference" / "telemetry"
# The page of what every command records.
README = "README"
# The package whose code logs the events of the reference; others' records are no event.
PACKAGE = "atlassian_offline_mcp"
# The fields that a line or an event holds whatever its event: its own, the run's, the
# span's, the traceback that ``log.exception`` adds.
STANDARD = frozenset(
    {"event", "level", "logger", "timestamp", "run", "command", "trace_id", "span_id"}
    | {"exc_info", "exception"}
)
# What an exported record's attributes hold besides its event's fields: its command, and
# the type, message and traceback of an exception, which the SDK adds.
EXPORTED = "command"
EXCEPTION = "exception."
# A placeholder in a documented name, such as ``<model>``, which stands for one word.
PLACEHOLDER = re.compile(r"<[a-z]+>")
# The kinds of span, as OTLP numbers them.
SPAN_KINDS = {1: "internal", 2: "server", 3: "client", 4: "producer", 5: "consumer"}


def rows(text: str, heading: str) -> list[list[str]]:
    """Give the cells of each row of the table under ``## heading``, its head aside."""
    section = text.partition(f"\n## {heading}\n")[2].partition("\n## ")[0]
    lines = [line for line in section.splitlines() if line.startswith("|")]
    return [[cell.strip() for cell in line.strip("|").split("|")] for line in lines[2:]]


def ticked(cell: str) -> list[str]:
    """Give what a cell holds in backticks, in order."""
    return re.findall(r"`([^`]+)`", cell)


@dataclass(frozen=True)
class Documented:
    """What a page lists: each event's fields, each span's kind and attributes, and more.

    A span is listed by its name, a placeholder in angle brackets standing for a word,
    such as ``<model>``; an instrument with its kind, unit and attributes.
    """

    events: dict[str, frozenset[str]]
    spans: dict[str, tuple[str, frozenset[str]]]
    instruments: dict[str, tuple[str, str, frozenset[str]]]


def documented(page: str) -> Documented:
    """Read the tables of a page of the reference, by its name without ``.md``."""
    text = (PAGES / f"{page}.md").read_text("utf-8")
    return Documented(
        {ticked(row[0])[0]: frozenset(ticked(row[2])) for row in rows(text, "Events")},
        {ticked(row[0])[0]: (row[1], frozenset(ticked(row[2]))) for row in rows(text, "Spans")},
        {
            ticked(row[0])[0]: (row[1], ticked(row[2])[0], frozenset(ticked(row[3])))
            for row in rows(text, "Instruments")
        },
    )


def pattern(name: str, command: str) -> re.Pattern[str]:
    """Give a listed span's name as the pattern that a recorded span's name matches whole.

    ``<command>`` stands for the command's name, another placeholder for any one word,
    such as ``<model>``.
    """
    return re.compile(PLACEHOLDER.sub(r"\\S+", re.escape(name.replace("<command>", command))))


def operations() -> list[str]:
    """Give the commands that the reference has a page for, found in its folder."""
    return sorted(path.stem for path in PAGES.glob("*.md") if path.stem != README)


@dataclass(frozen=True)
class Traced:
    """A span ended: its name, kind and attributes' keys, its ids, its parent's, its links'."""

    name: str
    kind: str
    attributes: frozenset[str]
    trace_id: int
    span_id: int
    parent: int  # the parent's span id, 0 for a root
    links: tuple[tuple[int, int], ...]  # each linked span's trace id and span id


@dataclass
class Emitted:
    """What runs recorded, gathered run after run.

    ``events`` holds each event's fields; ``logged`` each event logged, at its level,
    with the ids of the span it was logged in, 0 outside any, and its fields, sorted;
    ``records`` each record exported, by its body, the same ids and the keys of its
    attributes that are fields of its event, sorted; ``instruments`` each instrument's
    kinds and units, one of each unless runs disagree, and its attributes' keys.
    """

    events: defaultdict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    logged: list[tuple[str, int, int, int, tuple[str, ...]]] = field(default_factory=list)
    spans: list[Traced] = field(default_factory=list)
    instruments: defaultdict[str, tuple[set[tuple[str, str]], set[str]]] = field(
        default_factory=lambda: defaultdict(lambda: (set(), set()))
    )
    records: list[tuple[str, int, int, tuple[str, ...]]] = field(default_factory=list)

    def log(self, fields: dict[str, object], level: int, ids: tuple[int, int]) -> None:
        """Note an event logged, with its fields, at ``level``, in the span of ``ids``."""
        event = str(fields["event"])
        own = set(fields) - STANDARD
        self.events[event] |= own
        self.logged.append((event, level, *ids, tuple(sorted(own))))

    def export(self, body: str, ids: tuple[int, int], keys: Iterable[str]) -> None:
        """Note a record exported, by its body, in the span of ``ids``, and its attributes' keys."""
        fields = (key for key in keys if key != EXPORTED and not key.startswith(EXCEPTION))
        self.records.append((body, *ids, tuple(sorted(fields))))

    def measure(self, name: str, kind: str, unit: str, keys: Iterable[str]) -> None:
        """Note an instrument that recorded, of a kind and a unit, with its attributes' keys."""
        kinds, known = self.instruments[name]
        kinds.add((kind, unit))
        known.update(keys)

    @contextmanager
    def gathering(self, telemetry: InMemory, command: str) -> Iterator[None]:
        """Gather what is recorded within, in this process, by a run of ``command``.

        Its events reach the root logger, as do the records that ``Exported`` would send,
        to an in-memory exporter here; its spans and instruments, the SDK's providers of
        ``telemetry``, which hold nothing from before.
        """
        telemetry.spans.clear()
        telemetry.measured()
        exporter = InMemoryLogRecordExporter()
        provider = LoggerProvider(shutdown_on_exit=False)
        provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
        root = logging.getLogger()
        sinks = [Gathering(self), Exported(provider, command)]
        for sink in sinks:
            root.addHandler(sink)
        try:
            yield
        finally:
            for sink in sinks:
                root.removeHandler(sink)
        for exported in exporter.get_finished_logs():
            record = exported.log_record
            ids = (record.trace_id or 0, record.span_id or 0)
            self.export(str(record.body), ids, record.attributes or {})
        for span in telemetry.spans.get_finished_spans():
            context = span.get_span_context()
            self.spans.append(
                Traced(
                    span.name,
                    span.kind.name.lower(),
                    frozenset(span.attributes or {}),
                    context.trace_id,
                    context.span_id,
                    span.parent.span_id if span.parent else 0,
                    tuple((link.context.trace_id, link.context.span_id) for link in span.links),
                )
            )
        kinds = {Sum: "counter", Histogram: "histogram", Gauge: "gauge"}
        for name, metric in telemetry.measured().items():
            keys = {key for point in metric.data.data_points for key in point.attributes or {}}
            self.measure(name, kinds[type(metric.data)], metric.unit or "", keys)

    def collected(self, log_file: Path, collector: Collector) -> None:
        """Gather what a run in a fresh interpreter recorded: in its file, at the collector."""
        for line in (json.loads(text) for text in log_file.read_text("utf-8").splitlines()):
            if str(line["logger"]).partition(".")[0] == PACKAGE:
                level = logging.getLevelNamesMapping()[str(line["level"]).upper()]
                ids = (int(line.get("trace_id", "0"), 16), int(line.get("span_id", "0"), 16))
                self.log(line, level, ids)
        for _, record in collector.records():
            ids = (int.from_bytes(record.trace_id), int.from_bytes(record.span_id))
            self.export(str(plain(record.body)), ids, attributes(record.attributes))
        for span in collector.spans():
            self.spans.append(
                Traced(
                    span.name,
                    SPAN_KINDS[span.kind],
                    frozenset(attributes(span.attributes)),
                    int.from_bytes(span.trace_id),
                    int.from_bytes(span.span_id),
                    int.from_bytes(span.parent_span_id),
                    tuple(
                        (int.from_bytes(link.trace_id), int.from_bytes(link.span_id))
                        for link in span.links
                    ),
                )
            )
        for metric in collector.metrics():
            data = metric.WhichOneof("data")
            points = getattr(metric, data).data_points
            kind = "counter" if data == "sum" else data
            keys = {key for point in points for key in attributes(point.attributes)}
            self.measure(metric.name, kind, metric.unit, keys)


class Gathering(logging.Handler):
    """Note in ``Emitted`` each event of the program's code, with the span it is logged in."""

    def __init__(self, emitted: Emitted) -> None:
        """Note the events from DEBUG in ``emitted``."""
        super().__init__(logging.DEBUG)
        self.emitted = emitted

    @override
    def emit(self, record: logging.LogRecord) -> None:
        """Note the record, if it is an event of the program's code."""
        if record.name.partition(".")[0] == PACKAGE and isinstance(record.msg, dict):
            context = get_current_span().get_span_context()
            self.emitted.log(record.msg, record.levelno, (context.trace_id, context.span_id))


def undocumented(command: str, emitted: Emitted) -> list[str]:
    """Say how what runs of ``command`` recorded differs from its page and the README.

    Each event, span and instrument recorded must be listed, on the command's page or
    the README, with the fields, kind, attributes and unit recorded, or more; each that
    the command's page lists must have been recorded. Each event logged from INFO must
    have been exported, a record whose body is the event, with the ids of the span it
    was logged in and the event's fields as its attributes. Nothing differs when the
    list is empty.
    """
    own, every = documented(command), documented(README)
    events = every.events | own.events
    differences = [
        f"event not listed: {name}" for name in sorted(set(emitted.events) - set(events))
    ]
    differences += [
        f"event not recorded: {name}" for name in sorted(set(own.events) - set(emitted.events))
    ]
    differences += [
        f"event {name}: fields not listed: {sorted(fields - events[name])}"
        for name, fields in sorted(emitted.events.items())
        if name in events and fields - events[name]
    ]
    spans = every.spans | own.spans
    patterns = {name: pattern(name, command) for name in spans}
    for span in emitted.spans:
        names = [name for name, matching in patterns.items() if matching.fullmatch(span.name)]
        if len(names) != 1:
            differences.append(f"span not listed once: {span.name}")
            continue
        kind, keys = spans[names[0]]
        if span.kind != kind:
            differences.append(f"span {span.name}: {span.kind}, not {kind}")
        if span.attributes - keys:
            differences.append(f"span {span.name}: not listed: {sorted(span.attributes - keys)}")
    differences += [
        f"span not recorded: {name}"
        for name in sorted(own.spans)
        if not any(patterns[name].fullmatch(span.name) for span in emitted.spans)
    ]
    instruments = every.instruments | own.instruments
    for name, (kinds, keys) in sorted(emitted.instruments.items()):
        if name not in instruments:
            differences.append(f"instrument not listed: {name}")
            continue
        kind, unit, listed = instruments[name]
        if kinds != {(kind, unit)}:
            differences.append(f"instrument {name}: {sorted(kinds)}, not {kind} in {unit}")
        if keys - listed:
            differences.append(f"instrument {name}: not listed: {sorted(keys - listed)}")
    differences += [
        f"instrument not recorded: {name}"
        for name in sorted(set(own.instruments) - set(emitted.instruments))
    ]
    logged = Counter(
        (event, *ids) for event, level, *ids in emitted.logged if level >= logging.INFO
    )
    exported = Counter(record for record in emitted.records if record[0] in emitted.events)
    differences += [
        f"logged from INFO, not exported: {each}" for each in sorted((logged - exported).elements())
    ]
    differences += [
        f"exported, not logged from INFO: {each}" for each in sorted((exported - logged).elements())
    ]
    return differences
