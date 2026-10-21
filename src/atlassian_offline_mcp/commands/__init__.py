"""The subcommands: each module exposes ``register(subparsers)``.

``register`` adds the module's parser and sets its ``run`` default, a function that takes
the parsed arguments and returns the exit status. The command finds every module here,
so a plan adds a subcommand by adding a module, and parallel branches share no line. A
module whose name begins with ``_`` holds code that commands share, and is not one.

Every module is imported for ``--help``, with what it imports: every dependency is
declared, so each must import. ``_options`` gives the options that every command taking
settings shares.
"""
