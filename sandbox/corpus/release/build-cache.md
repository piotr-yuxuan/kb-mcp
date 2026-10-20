---
title: "Build cache troubleshooting"
---

# Build cache troubleshooting

Owner: Platform (release engineering). Last reviewed: 2026-05-28.

The build stage of Shipwright ([How code reaches production](deployment-pipeline.md)) uses a shared remote cache for image layers and downloaded dependencies. Entries are keyed by the service, the digest of the base image, and a hash of the lockfiles and of any files listed under `cache.inputs` in `shipwright.yaml`. A warm build of a typical Go service takes about 4 minutes; a cold one takes about 15.

When the cache works, nobody notices it. When it does not, the symptoms are confusing, so here is the list.

## Symptoms and fixes

| Symptom | Likely cause | What to do |
|---|---|---|
| The build is suddenly three or four times slower | A cache miss: the lockfile or the base image changed, or the entries were evicted | Expected after a dependency update; otherwise check the hit ratio (below) |
| The build passes but the image runs old code | A generated file is not part of the cache key | Add the file or its generator's inputs to `cache.inputs` |
| `error: cache entry corrupt` | An upload was interrupted | Build once with `--no-cache`; that writes a fresh entry |
| Works on your machine, fails in Shipwright | Your local cache hides a dependency that is not declared | Build locally without a cache and declare what is missing |
| A revert build behaves like the release it reverts | A stale layer was reused | Build with `--no-cache` and tell `#team-platform`, since that is a cache key bug |
| Every service's builds are slow at once | The cache service itself is degraded | Check the Lantern dashboard "Shipwright builds" before debugging your own service |

## Commands

```bash
# Build without reading the cache (it still writes fresh entries)
shipwright build merchant-api --no-cache

# Hit ratio and size for one service over the last 7 days
shipwright cache stats merchant-api

# Drop dependency entries for one service; affects every branch of that service
shipwright cache purge merchant-api --scope deps
```

Purging is rarely needed and makes the next build of every branch cold, so tell your team first.

## Watching it

The metric `shipwright_build_cache_hit_ratio` is on the "Shipwright builds" dashboard in Lantern, per service. Most services sit above 0.85. A service that stays below 0.5 usually has something in its cache key that changes on every commit, such as a timestamp written into a generated file, or a version string computed from the commit.

Entries that have not been used for 14 days are evicted, so the first build after a long quiet spell is cold. That is normal.

## Do not

- **Disable the cache permanently** in `shipwright.yaml`. It hides the real problem and adds ten minutes to every build for everyone waiting on yours.
- **Put secrets in image layers.** Secrets come from Strongroom at run time, never at build time. A layer containing a secret is cached and shared; if it happens, treat it as a leaked secret and follow [Playbook: leaked secret or API key](../security/leaked-secret.md).
- **Cache test results across builds.** The test stage always runs in full against the new image.
