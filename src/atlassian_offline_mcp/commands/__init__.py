"""The subcommands: each module exposes ``register(subparsers)``.

``register`` adds the module's parser and sets its ``run`` default, a function that takes
the parsed arguments and returns the exit status. The command finds every module here,
so a plan adds a subcommand by adding a module, and parallel branches share no line.
"""
