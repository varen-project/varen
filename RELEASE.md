# Release Process

This document describes how VAREN (MED-ALGo) releases are versioned, decided, and published. For the list of changes included in each release, see [CHANGELOG.md](CHANGELOG.md).

## Versioning

VAREN follows [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html) (`MAJOR.MINOR.PATCH`), as declared in [pyproject.toml](pyproject.toml):

* **MAJOR** — incompatible/breaking API or CLI changes.
* **MINOR** — backwards-compatible functionality (e.g. new algorithms, new CLI options).
* **PATCH** — backwards-compatible bug fixes.

The project is currently in initial development (`0.x.y`), so the public API may still change between minor versions without a major version bump, per SemVer's initial-development clause.

## Release Cadence

Releases occur on a scheduled basis as agreed to by the committers (see [GOVERNANCE.md](GOVERNANCE.md#release-process)). There is no fixed calendar cadence yet; releases are cut when there is a meaningful, stable set of changes accumulated in `CHANGELOG.md` under `[Unreleased]`.

## Who Can Release

Only the project's Lead and Co-Lead (see [GOVERNANCE.md](GOVERNANCE.md#current-leaders)) may cut a release.

## Release Procedure

1. **Confirm readiness** — ensure `main` is green (all tests pass: `python -m pytest tests/ -v`) and all intended changes are merged.
2. **Update the changelog** — move the relevant entries from the `[Unreleased]` section of [CHANGELOG.md](CHANGELOG.md) into a new dated version section, e.g.:
   ```markdown
   ## [0.2.0] - 2026-10-15
   ### Added
   ...
   ```
3. **Bump the version** — update the `version` field in [pyproject.toml](pyproject.toml) to match the new release.
4. **Commit and tag** — commit the version bump and changelog update, then create an annotated Git tag matching the version (e.g. `v0.2.0`).
5. **Build and verify the package** — build the distribution artifacts and confirm they install cleanly in a clean virtual environment.
6. **Publish the GitHub Release** — create a GitHub Release from the tag, using the corresponding CHANGELOG.md section as the release notes.
7. **Announce** — notify the community of the new release through the channels listed in [SUPPORT.md](SUPPORT.md).

## Support Policy

| Version        | Supported |
|----------------|-----------|
| Latest release | ✅        |
| Previous major | ❌        |
| Older versions | ❌        |

This mirrors the support policy declared in [SECURITY.md](SECURITY.md); only the latest release receives security fixes at this stage of the project.
