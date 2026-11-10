#!/usr/bin/env python3
# SPDX-License-Identifier: EUPL-1.2 OR GPL-3.0-or-later
"""Release the commit that CI has checked, in the workflow CD.

A release is two writes, in this order, and a run makes only those that are missing, so
that a second run finishes a run cut short:

    commit   the version commit on main, made through GitHub's API so that GitHub signs
             it: the version of `pyproject.toml` and of the package's entry in `uv.lock`
    release  the release X.Y.Z with its tag, on that commit

The version and the notes are pure functions, and so is the choice of the writes; the rest
reads git and calls `gh api`.  It needs Python 3.12 or later, git and gh, and runs at the
root of a checkout with every tag.

The environment: GH_TOKEN, for gh; GITHUB_REPOSITORY, GITHUB_SERVER_URL and
GITHUB_EVENT_NAME, from the runner; RELEASE_COMMIT and RELEASE_BUMP, from the workflow.

Status 0: released, or nothing to do, which it says.  Status 2, with one line on standard
error: an input is malformed, or git or GitHub refused a call, did not answer in time, or
answered something else.  No write follows the failure.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence

PROJECT_FILE = "pyproject.toml"
BRANCH = "main"
NUMBERS = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
VERSION = re.compile(NUMBERS)
# The whole message of a version commit.
VERSION_MESSAGE = re.compile(rf"Version ({NUMBERS})\n\n\[skip ci\]")
# The files that a version commit writes, each with the one line that holds the version:
# the project's, and the package's own entry in the lock, which `uv lock --check` compares.
VERSION_LINES = {
    PROJECT_FILE: re.compile(rb'^version = "[^"\n]*"$', re.MULTILINE),
    "uv.lock": re.compile(rb'(?<=^name = "kb-mcp"\n)version = "[^"\n]*"$', re.MULTILINE),
}
# The parts of a version, in the order of its numbers.
BUMPS = ("major", "minor", "patch")
COMMIT = re.compile(r"[0-9a-f]{40}")
MANUAL = "workflow_dispatch"
# What the environment must hold, and the shape of each value.
SETTINGS = {
    "GITHUB_REPOSITORY": re.compile(r"[\w.-]+/[\w.-]+", re.ASCII),
    "GITHUB_SERVER_URL": re.compile(r"https://[\w.-]+", re.ASCII),
    "GITHUB_EVENT_NAME": re.compile(rf"workflow_run|{MANUAL}"),
    "RELEASE_COMMIT": COMMIT,
    "RELEASE_BUMP": re.compile("|".join(BUMPS)),
}
# Seconds that one call of git or gh may last. The job's `timeout-minutes` bounds the run.
COMMAND_TIMEOUT_SECONDS = 120
CHANGES = {"A": "Added", "D": "Removed"}
VERSION_COMMIT = """
mutation ($input: CreateCommitOnBranchInput!) {
  createCommitOnBranch(input: $input) { commit { oid } }
}
"""
RELEASE_OF_TAG = """
query ($owner: String!, $name: String!, $tag: String!) {
  repository(owner: $owner, name: $name) { release(tagName: $tag) { tagName } }
}
"""


class ReleaseError(Exception):
    """An input that cannot be trusted as written, or a command that failed."""


@dataclass(frozen=True)
class Commit:
    """A commit, as far as a version commit is told by it."""

    hash: str
    parents: tuple[str, ...]
    message: str
    changed: frozenset[str]  # the paths that differ from its first parent


@dataclass(frozen=True)
class Found:
    """What a run finds before it writes anything."""

    commit: Commit  # the commit that this run is about
    head: Commit  # main on origin
    pending: Commit | None  # a version commit that an earlier run may have left unreleased
    released: bool  # whether GitHub holds the release of `pending`
    version: str  # the version of `pyproject.toml` at `commit`
    tags: Mapping[str, str]  # the commit of each tag of origin, by name


@dataclass(frozen=True)
class Decision:
    """The writes that are missing: none when `version` is None, and `note` says why."""

    version: str | None = None
    base: str | None = None  # the commit that the notes describe and the version commit is on
    made: str | None = None  # the version commit, when an earlier run made it
    note: str = ""


def project_version(text: bytes) -> str:
    """Return the version of a `pyproject.toml`, refused unless it is MAJOR.MINOR.PATCH."""
    try:
        version = tomllib.loads(text.decode())["project"]["version"]
    except (UnicodeError, tomllib.TOMLDecodeError, KeyError, TypeError) as error:
        message = f"{PROJECT_FILE} has no readable project.version: {error}"
        raise ReleaseError(message) from error
    if not (isinstance(version, str) and VERSION.fullmatch(version)):
        message = f"{PROJECT_FILE} has the version {version!r}, not MAJOR.MINOR.PATCH"
        raise ReleaseError(message)
    return version


def next_version(current: str, tags: Collection[str], bump: str) -> str:
    """Return the version to release, from the project's version and the bump asked.

    The part that `bump` names is raised and the parts after it go back to zero.  A version
    that has its tag already is never given twice.
    """
    raised = BUMPS.index(bump)
    numbers = [int(number) for number in current.split(".")]
    numbers = [*numbers[:raised], numbers[raised] + 1, *[0] * (2 - raised)]
    version = ".".join(str(number) for number in numbers)
    if version in tags:
        message = f"the tag {version} exists already"
        raise ReleaseError(message)
    return version


def release_notes(changes: Sequence[tuple[str, str]], compare: str | None) -> str:
    """Write the notes of a release in Markdown, from the diff since the release before.

    `changes` holds what `git diff --name-status` says: a status letter and a path.
    `compare` is the link to that comparison, and None for a first release.
    """
    if compare is None:
        return "First release.\n"
    if not changes:
        return f"No file changed.\n\nFull difference: {compare}\n"
    rows = [
        "| {} | `{}` |".format(CHANGES.get(status, "Changed"), path.replace("|", "\\|"))
        for status, path in changes
    ]
    return "\n".join(
        ["| Change | File |", "|---|---|", *rows, "", f"Full difference: {compare}", ""]
    )


def with_version(path: str, text: bytes, version: str) -> bytes:
    """Set the version line of a file that a version commit writes, every other byte kept."""
    written, count = VERSION_LINES[path].subn(f'version = "{version}"'.encode(), text)
    if count != 1:
        message = f"{path} has {count} version lines where one is expected"
        raise ReleaseError(message)
    return written


def written_version(commit: Commit) -> str | None:
    """Return the version that `commit` writes, or None when it is no version commit."""
    message = VERSION_MESSAGE.fullmatch(commit.message)
    if message is None or len(commit.parents) != 1 or commit.changed != frozenset(VERSION_LINES):
        return None
    return message[1]


def decide(found: Found, bump: str) -> Decision:
    """Choose the writes that are missing."""
    moved = found.head.hash != found.commit.hash
    made = found.pending
    if made is None and moved:
        note = (
            f"{BRANCH} has moved past {found.commit.hash} and its next commit is no version"
            " commit: the run of the newer push releases"
        )
        return Decision(note=note)
    if made is not None:
        version = written_version(made)
        if not found.released:
            if found.tags.get(version, made.hash) != made.hash:
                message = f"the tag {version} is on another commit than the version commit"
                raise ReleaseError(message)
            return Decision(version=version, base=made.parents[0], made=made.hash)
        if moved:
            return Decision(note=f"{version} is released already")
    return Decision(
        version=next_version(found.version, found.tags, bump),
        base=found.commit.hash,
    )


def run(*command: str, stdin: bytes = b"") -> bytes:
    """Return what a command prints; any failure stops the release."""
    result = subprocess.run(  # noqa: S603 git and gh, with arguments this script builds
        command,
        input=stdin,
        capture_output=True,
        check=False,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        reason = result.stderr.decode(errors="replace").strip()
        message = f"{' '.join(command)} failed: {reason}"
        raise ReleaseError(message)
    return result.stdout


def api(method: str, path: str, body: object = None) -> object:
    """Send one request to GitHub with `gh api` and return its parsed reply."""
    arguments, sent = ["gh", "api", "--method", method, path], b""
    if body is not None:
        arguments, sent = [*arguments, "--input", "-"], json.dumps(body).encode()
    reply = run(*arguments, stdin=sent)
    try:
        return json.loads(reply)
    except ValueError as error:
        message = f"{method} {path}: the reply is not JSON"
        raise ReleaseError(message) from error


def dig(reply: object, *keys: str) -> object:
    """Follow keys into a parsed reply."""
    found = reply
    for key in keys:
        if not isinstance(found, dict) or key not in found:
            message = f"unexpected reply: no {'.'.join(keys)} in {reply!r}"
            raise ReleaseError(message)
        found = found[key]
    return found


def has_release(repository: str, version: str) -> bool:
    """Tell whether GitHub holds the release of `version`."""
    owner, name = repository.split("/")
    variables = {"owner": owner, "name": name, "tag": version}
    reply = api("POST", "graphql", {"query": RELEASE_OF_TAG, "variables": variables})
    release = dig(reply, "data", "repository", "release")
    if release is not None and release != {"tagName": version}:
        message = f"unexpected reply: the release of {version} is {release!r}"
        raise ReleaseError(message)
    return release is not None


def confirm_ci(repository: str, head: Commit) -> None:
    """Stop unless CI succeeded on main's head, or on its parent if that is a version commit."""
    checked = head.parents[0] if written_version(head) else head.hash
    reply = api(
        "GET",
        f"repos/{repository}/actions/workflows/ci.yml/runs"
        f"?head_sha={checked}&event=push&branch={BRANCH}&status=success",
    )
    runs = dig(reply, "workflow_runs")
    if not isinstance(runs, list):
        message = f"unexpected reply: the runs of CI are not a list but {runs!r}"
        raise ReleaseError(message)
    if not any(
        isinstance(found, dict)
        and found.get("head_sha") == checked
        and found.get("conclusion") == "success"
        for found in runs
    ):
        message = f"CI has not succeeded on {checked}"
        raise ReleaseError(message)


def read_commit(name: str) -> Commit:
    """Read what git says of one commit, as far as a version commit is told by it."""
    commit, *parents = run("git", "rev-list", "-n", "1", "--parents", name).decode().split()
    changed = run("git", "diff-tree", "-r", "-z", "--name-only", "--no-commit-id", "--root", commit)
    return Commit(
        hash=commit,
        parents=tuple(parents),
        message=run("git", "log", "-n", "1", "--format=%B", commit).decode().rstrip("\n"),
        changed=frozenset(changed.decode().split("\0")) - {""},
    )


def read(repository: str, name: str) -> Found:
    """Read what origin and GitHub hold, once fetched, around the commit `name`."""
    origin = f"refs/remotes/origin/{BRANCH}"
    run("git", "fetch", "--quiet", "--tags", "origin", f"+refs/heads/{BRANCH}:{origin}")
    head = read_commit(origin)
    commit = read_commit(name)
    tags = {}
    listed = run(
        "git",
        "for-each-ref",
        "--format=%(refname:lstrip=2) %(objectname) %(*objectname)",
        "refs/tags",
    )
    for line in listed.decode().splitlines():
        # An annotated tag has two objects, and its commit is the second.
        tag, *objects = line.split()
        tags[tag] = objects[-1]
    # A version commit left without its release is the commit itself, or what comes next.
    candidate = commit
    if head.hash != commit.hash:
        span = f"{commit.hash}..{head.hash}"
        following = run("git", "rev-list", "--first-parent", "--reverse", span).decode().split()
        candidate = read_commit(following[0]) if following else None
        if candidate is not None and candidate.parents != (commit.hash,):
            candidate = None
    version = written_version(candidate) if candidate is not None else None
    return Found(
        commit=commit,
        head=head,
        pending=candidate if version is not None else None,
        released=version is not None and has_release(repository, version),
        version=project_version(run("git", "show", f"{commit.hash}:{PROJECT_FILE}")),
        tags=tags,
    )


def release(environment: Mapping[str, str]) -> str:
    """Make the writes that are missing, and return what was done."""
    malformed = [
        name for name, shape in SETTINGS.items() if not shape.fullmatch(environment.get(name, ""))
    ]
    if malformed:
        message = f"missing or malformed in the environment: {', '.join(malformed)}"
        raise ReleaseError(message)
    repository, server, event, commit, bump = (environment[name] for name in SETTINGS)
    found = read(repository, commit)
    if event == MANUAL:
        confirm_ci(repository, found.head)
    decision = decide(found, bump)
    if decision.version is None:
        return decision.note
    # Everything that may fail to read is read before the first write.
    version, base, target = decision.version, decision.base, decision.made
    numbers = tuple(map(int, version.split(".")))
    earlier = [
        parsed
        for tag in found.tags
        if (match := VERSION.fullmatch(tag))
        and (parsed := tuple(map(int, match.groups()))) < numbers
    ]
    changes, compare = [], None
    if earlier:
        previous = ".".join(map(str, max(earlier)))
        difference = ("diff", "--name-status", "--no-renames", "-z", previous, base)
        fields = run("git", *difference).decode().split("\0")[:-1]
        changes = list(zip(fields[::2], fields[1::2], strict=True))
        compare = f"{server}/{repository}/compare/{previous}...{version}"
    notes = release_notes(changes, compare)
    if target is None:
        additions = [
            {
                "path": path,
                "contents": base64.b64encode(
                    with_version(path, run("git", "show", f"{base}:{path}"), version)
                ).decode(),
            }
            for path in VERSION_LINES
        ]
        change = {
            "branch": {"repositoryNameWithOwner": repository, "branchName": BRANCH},
            # GitHub refuses the commit on a branch that has moved since this run's read.
            "expectedHeadOid": base,
            "message": {"headline": f"Version {version}", "body": "[skip ci]"},
            "fileChanges": {"additions": additions},
        }
        made = api("POST", "graphql", {"query": VERSION_COMMIT, "variables": {"input": change}})
        target = dig(made, "data", "createCommitOnBranch", "commit", "oid")
        if not (isinstance(target, str) and COMMIT.fullmatch(target)):
            message = f"unexpected reply: the version commit is {target!r}"
            raise ReleaseError(message)
    api(
        "POST",
        f"repos/{repository}/releases",
        {"tag_name": version, "target_commitish": target, "name": version, "body": notes},
    )
    return f"released {version} on {target}"


def main() -> int:
    """Run one release: 0 when released or when there is nothing to do, 2 otherwise."""
    try:
        done = release(os.environ)
    except (ReleaseError, subprocess.TimeoutExpired, OSError, UnicodeError) as error:
        sys.stderr.write(f"release: {error}\n")
        return 2
    sys.stdout.write(f"release: {done}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
