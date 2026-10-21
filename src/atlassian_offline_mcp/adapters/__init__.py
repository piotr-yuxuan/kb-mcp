"""Effects: the network, the browser, files and SQLite, behind narrow functions."""

import os

# onnxruntime, which adapters.embedding imports, sends usage telemetry to Microsoft from
# native code, through any proxy, some seconds after its first import, unless this is
# set before that import. The server and the index open no network connection: this
# package is loaded before any of its modules, so it is set here.
os.environ["ORT_DISABLE_TELEMETRY"] = "1"
