"""The subcommands: each module exposes ``register(subparsers)`` and ``run``.

``register`` adds the module's parser and sets its ``command`` default, a
``cli.domain.command.Command`` that names the module and the settings its flags
override. The entry, ``_shared.enter``, loads the settings and calls the module's
``run(arguments, settings)``, which returns the exit status. The command finds every
module here, so a plan adds a subcommand by adding a module, and parallel branches
share no line. A module whose name begins with ``_`` holds code that commands share,
and is not one.

Every module is imported for ``--help``, with what it imports: every dependency is
declared, so each must import. ``_options`` gives the options that every command taking
settings shares.
"""
