"""The subcommands' runs: each module exposes ``run(arguments, loaded)`` and ``text``.

The entry, ``_shared.enter``, loads the settings with the flags given, then imports the
module that the chosen subcommand's ``Command`` names, alone, and calls its ``run`` with
the settings loaded (``config.domain.settings.Loaded``). It returns the exit status and
the result, or None when it has none to write. The entry writes the result as JSON, or
as ``text(result, detail)`` gives it, short or detailed. A module whose name begins
with ``_`` holds code that runs share.
"""
