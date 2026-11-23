"""What a run tells of itself: structured logs, progress, traces and metrics.

OpenTelemetry's variables, but the two that the settings read, leave the environment here,
before the API or the SDK reads one: a provider or a sampler named would change the run.
"""

import os

# OpenTelemetry's variables that the settings read.
READ = frozenset({"OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_SDK_DISABLED"})
# The OpenTelemetry SDK's loggers, whose records go to the file alone: on stderr they
# would break -q, and exported, a failed export would log about itself.
SDK = "opentelemetry"

for name in [name for name in os.environ if name.startswith("OTEL_") and name not in READ]:
    del os.environ[name]
