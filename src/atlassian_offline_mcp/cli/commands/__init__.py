"""The subcommands' runs: each module exposes ``run(arguments, settings)``.

The entry, ``_shared.enter``, loads the settings with the flags given, then imports the
module that the chosen subcommand's ``Command`` names, alone, and calls its ``run``,
which returns the exit status. A module whose name begins with ``_`` holds code that
runs share.
"""
