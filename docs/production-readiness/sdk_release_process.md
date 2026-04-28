# SDK Release Process

This document defines the repo-controlled release process for the first-party Nexus AI SDKs.

## Goals

- Bind every publish operation to a semver tag.
- Reject releases when tag and package metadata drift.
- Produce publishable artifacts before any registry push.
- Keep Python, TypeScript, and Go release motions explicit and auditable.

## Tag Conventions

- Python: `sdk/python/vX.Y.Z`
- TypeScript: `sdk/typescript/vX.Y.Z`
- Go: `sdk/go/vX.Y.Z`

Each tag is validated by `scripts/verify_sdk_release.py` before publication steps run.

## Validation Gates

### Python

- Tag matches `sdk/python/nexus_ai_sdk/_version.py`
- Required package files exist: `README.md`, `CHANGELOG.md`, `LICENSE`, `pyproject.toml`
- `python -m build` succeeds
- `python -m twine check dist/*` succeeds
- `tests/test_sdk_packaging.py` passes

### TypeScript

- Tag matches `sdk/typescript/package.json`
- Required package files exist: `README.md`, `CHANGELOG.md`, `package.json`, `tsconfig.json`
- `npm install`, `npm run build`, and `npm run typecheck` succeed
- `npm pack --dry-run` succeeds

### Go

- Tag matches `sdk/go/nexusai/operator.go` `SDKVersion`
- Required package files exist: `README.md`, `go.mod`, `nexusai/client.go`, `nexusai/operator.go`
- `go test ./...` succeeds
- `pkg.go.dev` publication is driven by the pushed module tag

## Publication Paths

- Python publishes to PyPI via trusted publishing in `.github/workflows/sdk-publish.yml`
- TypeScript publishes to npm using `NPM_TOKEN` in `.github/workflows/sdk-publish.yml`
- Go does not require a registry upload step; `pkg.go.dev` indexes the pushed module tag automatically

## Manual Dry Run

Use `workflow_dispatch` on `.github/workflows/sdk-publish.yml` with:

- `sdk_target`: `python`, `typescript`, or `go`
- `tag_name`: the target semver tag
- `publish`: `false`

This runs the same verification and build gates without publishing.

## Operator Rule

Do not publish SDKs from arbitrary branches or untagged commits. All releases must originate from the tag-driven workflow so the registry state always has a corresponding immutable source tag and validation report.