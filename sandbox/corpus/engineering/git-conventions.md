---
title: "Git conventions"
---

# Git conventions

Owner: Platform team. Last reviewed: 2026-08-26.

These conventions hold in every team repository ([ADR-005](../architecture/adr-005-repository-per-team.md)). The code host enforces the branch protections; reviewers check the rest, as the [code review guidelines](code-review.md) describe.

## Branches

- `main` is the only long-lived branch. It is protected: no direct pushes, no force-pushes, and merges only through a reviewed change with green CI.
- Work happens on short-lived branches named after the Jira ticket, in lower case, followed by a slug:

```text
eng-NNNN-batch-size-config   ticket work
spike/kafka-batch-consumer   experiments that will never merge
```

- A branch lives for days, not weeks. Rebase it on `main` at least once a day while it is open.
- The code host deletes the branch after merge; leave the box ticked.

## Commit messages

The title is in the imperative and in sentence case, 50 characters at most, with no full stop. The body, after a blank line and wrapped at 72 characters, says why the change was needed and anything a future reader would otherwise lose: the constraint you hit, the alternative you rejected. The Jira ticket goes in a trailer.

```text
Read the payout batch size from configuration

The size was a constant in three modules, so changing it meant
editing all three and hoping none was missed. Reading it once at
start-up lets Payouts set it per environment.

Refs: ENG-NNNN
```

Good titles: "Add idempotency key to refund creation", "Remove the retired fx-quote cache flag". Titles we send back: "fixed stuff", "WIP", "address review comments", "more changes".

## Merging

Changes are squash-merged. The squashed commit takes the change's title and description, so write those as you would a commit message. During review, push follow-up commits rather than rewriting history, so that reviewers can see what changed since they last looked. Before review starts, rebase and tidy as much as you like.

Never merge `main` into a feature branch; rebase instead:

```bash
git fetch origin
git rebase origin/main
git push --force-with-lease
```

`--force-with-lease` refuses to overwrite commits that someone else pushed to your branch since you last fetched. Never use a plain `--force`.

## Signing

Commits on `main` are signed. Set up SSH signing once on your laptop, and register the same public key with the code host as a signing key:

```bash
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_ed25519.pub
git config --global commit.gpgsign true
```

## Tags and releases

Shipwright creates release tags when it builds a release, in the form `<service>-<version>`, for example `payout-gateway-4.13.0`. Do not create or move release tags by hand; Shipwright treats a moved tag as a different release. To undo a release that has already gone out, follow [reverting a bad release](../release/reverting-a-release.md).

## What never goes in a repository

- Secrets of any kind. The scanner in CI blocks them, and one that slips through is handled under [leaked secret or API key](../security/leaked-secret.md).
- Production data, including extracts that someone believes are anonymised.
- Large binaries. Models belong in the model registry, and datasets in the warehouse.
- Personal editor and operating system files. Put those patterns in your global Git ignore file, not in the repository's `.gitignore`.
