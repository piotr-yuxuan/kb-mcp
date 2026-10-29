"""The subcommands' declarations: each module exposes ``register(subparsers)``.

``register`` adds the subcommand's parser, with its help and options, and sets its
``command`` default, a ``cli.domain.command.Command`` that names the module of
``cli.commands`` running it. The command finds every module here, so a plan adds a
subcommand by adding a module here and its run there, and parallel branches share no
line. A module whose name begins with ``_`` holds options that commands share, and is
not one.

Every module here is imported for ``--help``, so none imports what a run needs:
contract G keeps the runs' packages out, even indirectly.
"""
