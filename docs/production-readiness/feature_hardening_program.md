# Feature Hardening Program

This file starts the post-closure hardening track for the currently implemented Nexus AI surface area.

## Initial Scope

The first hardening slice covers high-value regression surfaces already marked implemented:

- SDK packaging and client contract stability
- governance and safety enforcement regression

The smoke tier is intentionally conservative for day-one reliability:

- `tests/test_sdk_packaging.py`
- `tests/test_governance_hardening.py`

The broader nightly tier extends coverage to:

- OpenAI-compatible v1 API contracts
- feature-hardening endpoint lifecycle coverage
- provider routing reliability
- validation, model-update, and observability regressions

## Execution Path

- Local runner: `scripts/run_feature_hardening_suite.py`
- CI workflow: `.github/workflows/feature-hardening.yml`
- Report artifact: `test-results/feature-hardening-report.json`

## Suite Levels

- `smoke`: fast release-blocking regression subset
- `full`: broader nightly hardening subset including validation, model-update, and observability coverage

## Acceptance Rule

Hardening has officially started once the workflow and local runner are present and producing versioned reports. New hardening slices should extend the suite list rather than fork separate ad hoc workflows unless the runtime or dependency profile requires isolation.

## Relationship To External Gates

The remaining external/process-bound items are already at `G2` or above in `docs/production-readiness/external_progress_gates.md`. That makes them eligible for parallel internal hardening even though they are not yet complete.