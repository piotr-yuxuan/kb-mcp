# Security policy

## Existing tooling

GitHub Actions runs [the checks](workflows/ci.yml) on every push and pull request, on
Linux and macOS: Ruff, the import contracts and the test suite. The suite holds that no
run logs or leaves a secret, that commands stay off the network but for the hosts they
are given, that text from the site shows on a terminal and does nothing, and that the
server marks what it copies from Confluence, Jira and the work log as untrusted
reference data. No vulnerability scanner runs on this repository, and its dependencies,
pinned in `uv.lock`, are updated by hand.

[The credentials](../docs/explanation/credentials.md) describe the security model: where
each secret is kept and sent, what agents get, and what none of it guards against.

## Supported versions

Only the latest
[release](https://github.com/piotr-yuxuan/atlassian-offline-mcp/releases) is supported.
This package is pre-release, so a fix reaches no earlier version.

## Reporting a vulnerability

Open an issue, or contact the [code owners](./CODEOWNERS) on social media. Never put a
token, a cookie or a site's content in an issue.
