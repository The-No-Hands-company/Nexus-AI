# nostack — The Nexus AI Engineering Team

nostack turns Nexus AI into a virtual engineering team. CEO → Eng Manager → Designer → Reviewer → QA → Release Engineer — 23 specialists across 8 workflows, all as Nexus AI specialist agents and personas.

## Quick Start

1. `./nostack/setup` — registers all nostack specialists in your Nexus AI instance
2. Chat with Nexus AI: "Run `/office-hours` — I want to build a daily briefing app"
3. Chain the sprint: `/plan-ceo-review` → `/plan-eng-review` → `/review` → `/qa` → `/ship`

## The Sprint: Think → Plan → Build → Review → Test → Ship → Reflect

Each skill feeds into the next:

| Phase | Skill | Specialist |
|-------|-------|------------|
| Think | `/office-hours` | YC Office Hours — 6 forcing questions |
| Plan | `/plan-ceo-review` | CEO / Founder — rethink scope |
| Plan | `/plan-eng-review` | Eng Manager — architecture & tests |
| Plan | `/plan-design-review` | Senior Designer — 0-10 audit |
| Design | `/design-consultation` | Design Partner — system from scratch |
| Design | `/design-shotgun` | Design Explorer — 4-6 variants |
| Design | `/design-html` | Design Engineer — production HTML |
| Build | `/autoplan` | Review Pipeline — CEO→design→eng auto |
| Review | `/review` | Staff Engineer — find prod bugs |
| Review | `/investigate` | Debugger — root cause analysis |
| Review | `/design-review` | Designer Who Codes — audit + fix |
| Review | `/devex-review` | DX Tester — live DX audit |
| Test | `/qa` | QA Lead — browser test + fix + verify |
| Test | `/qa-only` | QA Reporter — bug report only |
| Ship | `/ship` | Release Engineer — PR + coverage |
| Ship | `/land-and-deploy` | Release Engineer — merge + deploy |
| Ship | `/canary` | SRE — post-deploy monitoring |
| Ship | `/benchmark` | Performance Engineer — page metrics |
| Reflect | `/retro` | Eng Manager — weekly retrospective |
| Security | `/cso` | Chief Security Officer — OWASP + STRIDE |
| Docs | `/document-release` | Technical Writer — update all docs |
| Docs | `/document-generate` | Documentation Author — Diataxis |

### Power Tools

| Skill | What it does |
|-------|-------------|
| `/careful` | Warns before destructive commands |
| `/freeze` | Restrict edits to one directory |
| `/guard` | /careful + /freeze combined |
| `/unfreeze` | Remove freeze boundary |
| `/codex` | Second opinion from external model |
| `/diagram` | English → editable diagram |
| `/make-pdf` | Markdown → publication-quality PDF |
| `/learn` | Cross-session learning management |
| `/spec` | Vague intent → executable spec |

## How It Works

Each skill is a Nexus AI **SpecialistAgent** registered in `src/agents/registry.py`. When you invoke a skill, Nexus AI loads the agent's persona and system prompt, giving it the specialized methodology, constraints, and output format from the skill file.

Skills chain naturally — `/office-hours` writes a design doc that `/plan-ceo-review` reads. `/plan-eng-review` writes a test plan that `/qa` picks up.

## Architecture

```
nostack/
├── README.md          # This file
├── setup              # Registration script
├── bin/               # CLI tools
│   ├── nostack-setup
│   └── nostack-run
└── skills/            # Skill personas
    ├── office-hours.md
    ├── plan-ceo-review.md
    ├── plan-eng-review.md
    ├── plan-design-review.md
    ├── design-consultation.md
    ├── design-shotgun.md
    ├── design-html.md
    ├── design-review.md
    ├── devex-review.md
    ├── autoplan.md
    ├── review.md
    ├── investigate.md
    ├── qa.md
    ├── qa-only.md
    ├── ship.md
    ├── land-and-deploy.md
    ├── canary.md
    ├── benchmark.md
    ├── cso.md
    ├── document-release.md
    ├── document-generate.md
    ├── retro.md
    ├── careful.md
    ├── freeze.md
    ├── guard.md
    ├── unfreeze.md
    ├── codex.md
    ├── diagram.md
    ├── make-pdf.md
    ├── learn.md
    └── spec.md
```

## Adding nostack to a Project

```bash
cd your-project
python nostack/setup --project
git add nostack/ .nexus/
git commit -m "add nostack virtual engineering team"
```
