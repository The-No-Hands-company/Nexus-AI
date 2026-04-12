# Nexus AI Project Refactor Plan

## Goal

Make Nexus AI easier for contributors to understand, run, and extend by adopting a clearer project architecture, stronger module separation, and contributor-friendly onboarding.

## Principles

- Separate concerns cleanly: API, agent core, tools, provider adapters, memory, storage, and UI should each have a clear home.
- Keep the default deployment path simple: `docker compose up` should still work out of the box.
- Preserve existing semantics while reorganising code.
- Add documentation and examples for the most common contributor workflows.
- Avoid over-engineering: one repo, one Python package, clear boundaries.

## Proposed structure

```
Nexus-AI/
├── README.md
├── LICENSE
├── CHANGELOG.md
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── SECURITY.md
├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md
│   │   └── feature_request.md
│   └── pull_request_template.md
├── docs/
│   ├── ARCHITECTURE.md
│   ├── PROJECT_REFACTOR_PLAN.md
│   ├── ROADMAP.md
│   ├── ROADMAP_FEATURES_V2.md
│   ├── SECURITY.md
│   ├── SOVEREIGN_MODEL_PLAN.md
│   ├── STRATEGY_AND_GUARDRAILS.md
│   └── VERSAAI_PORTING_TRACKER.md
├── src/
│   ├── __init__.py
│   ├── app.py
│   ├── agent.py
│   ├── autonomy.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py
│   │   └── schemas.py
│   ├── providers/
│   │   ├── __init__.py
│   │   └── model_router.py
│   ├── tools/
│   │   ├── __init__.py
│   │   └── builtin.py
│   ├── memory.py
│   ├── personas.py
│   ├── thinking.py
│   ├── db.py
│   └── rag/
│       ├── __init__.py
│       ├── ingest.py
│       └── query.py
├── tests/
│   ├── test_api.py
│   ├── test_agent.py
│   └── test_tools.py
├── static/
└── requirements.txt
```

## Recommended refactor phases

### Phase 1 — Documentation and repo hygiene

- Keep `README.md` updated with docs links and getting-started guidance.
- Add `.github/` issue and PR templates.
- Add OSS-friendly docs: `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`, `LICENSE`.
- Move internal planning docs to `docs/` (already done).

### Phase 2 — Code layout refactor

- Create `src/` package and move application modules under it.
- Keep `main.py` as a lightweight entrypoint that imports `src.app` or `src.api.routes`.
- Split API route definitions into `src/api/routes.py` and schemas into `src/api/schemas.py`.
- Move provider selection into `src/providers/model_router.py` and provider adapters into `src/providers/`.
- Move tools into `src/tools/builtin.py` and reserve `src/tools/` for new tool categories.
- Keep `rag/` as a subpackage under `src/` and rename to `src/rag/`.
- Add `tests/` for unit/integration coverage.

### Phase 3 — Onboarding improvements

- Add `docs/development.md` describing local dev, test, and Docker workflows.
- Add a minimal `devcontainer.json` or GitHub Codespaces recommendation.
- Add a `scripts/` folder with helper commands for linting and test execution.
- Create `docs/ARCHITECTURE.md` with the current component design and request lifecycle (already done).

### Phase 4 — Dependency and package management

- Consider a `pyproject.toml` later for Poetry / PDM packaging if the repo wants to support installable packages.
- Keep `requirements.txt` for now to preserve compatibility with the existing Docker setup.

## Suggested immediate improvements

- Rename `main.py` → `src/app.py` and keep `main.py` as a thin shim.
- Keep `README.md` as the user-facing entrypoint and move developer docs into `docs/`.
- Add `tests/` with one smoke test for `GET /v1/models` and one for `POST /chat`.
- Add a `docs/roadmap_summary.md` if the roadmap is too large for casual contributors.

## Notes

This plan is designed to preserve the current codebase while making it easier for future contributors to find the right files and understand how the system works. The most valuable next step is to create tests around the existing behavior before moving files.
