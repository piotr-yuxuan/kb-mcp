"""What a run tells of itself: structured logs, progress, traces and metrics.

Of OpenTelemetry's variables, which other programs share, a run reads two alone, by its
settings: ``OTEL_EXPORTER_OTLP_ENDPOINT`` and ``OTEL_SDK_DISABLED``. Every other is taken
out of the process's environment here, before any module of this context imports
OpenTelemetry, as the API and the SDK read some on their import or at the first call for
a provider: one naming a provider would install the SDK with telemetry off, or end the
run if unknown, and a sampler could drop every trace.
"""

import os

# OpenTelemetry's variables that the settings read.
READ = frozenset({"OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_SDK_DISABLED"})

for name in [name for name in os.environ if name.startswith("OTEL_") and name not in READ]:
    del os.environ[name]
