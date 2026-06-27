# nostack — The Nexus AI Virtual Engineering Team

nostack turns Nexus AI into a virtual engineering team. 31 specialist agents across 8 workflows, callable via REST API, Python/TypeScript/Go SDKs, CLI, WebSocket, and SSE streaming.

## Quick Start

```bash
# Install nostack into Nexus AI
make nostack-install

# List all skills
make nostack-list

# Get skill recommendations for a task
make nostack-suggest TASK="audit my codebase for security vulnerabilities"

# Run a full sprint
python nostack/bin/nostack-run --sprint "Build REST API" --skills "office-hours,plan-eng-review,review,ship"
```

## Architecture

```
Task → classify → recommend skills
                   ↓
            Sprint (chain skills)
                   ↓
         Run skill(s) via API/WS/SSE
                   ↓
         Results + persist for resume
```

## API Reference

### Skill Discovery

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/nostack/skills` | List all 31 skills |
| GET | `/nostack/skills/{name}` | Get skill prompt and metadata |
| POST | `/nostack/skills/classify` | Recommend skills from task description |

### Skill Execution

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/nostack/skills/{name}/run` | Run a skill synchronously |
| GET | `/nostack/skills/{name}/stream?task=...` | SSE streaming execution |
| WS | `/nostack/skills/{name}/stream` | WebSocket real-time streaming |

### Sprint Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/nostack/sprint` | Start sprint (async, returns sprint_id) |
| GET | `/nostack/sprint/{id}` | Check sprint status/progress |
| POST | `/nostack/sprint/{id}/resume` | Resume interrupted sprint |
| GET | `/nostack/sprints` | List recent sprints |
| DELETE | `/nostack/sprint/{id}` | Cancel running sprint |

### Templates & Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/nostack/templates` | List 7 sprint templates |
| GET | `/nostack/health` | System health with stats |

## SDK Usage

### Python
```python
from nexus_ai_sdk import NexusAIClient
client = NexusAIClient(base_url="http://localhost:8000")

# Classify task → get skill recommendations
recs = client.classify_nostack_task("audit my codebase for security")
# → [/cso (2), /review (2)]

# Run a sprint
sprint = client.run_nostack_sprint("Fix auth bug",
    ["investigate", "review", "ship"])
status = client.get_nostack_sprint(sprint["sprint_id"])
```

### TypeScript
```typescript
const client = new NexusAIClient("http://localhost:8000");
const skills = await client.listNostackSkills();
const result = await client.runNostackSkill("office-hours", "build a daily briefing app");
```

### Go
```go
client := nexusai.NewClient("http://localhost:8000", "")
skills, _ := client.ListNostackSkills()
recs, _ := client.ClassifyNostackTask("audit my codebase", 5)
```

### REST
```bash
curl -X POST http://localhost:8000/nostack/skills/classify \
  -H "Content-Type: application/json" \
  -d '{"task": "design a landing page"}'

curl -X POST http://localhost:8000/nostack/sprint \
  -H "Content-Type: application/json" \
  -d '{"task": "Build API", "skills": ["office-hours", "review", "ship"]}'
```

## Sprint Templates

| Template | Skills | Use Case |
|----------|--------|----------|
| feature | office-hours → ceo-review → eng-review → review → qa → ship | New feature end-to-end |
| bugfix | investigate → review → ship | Bug hunting and fixing |
| security | cso → review → ship | Security audit + remediation |
| design | consultation → shotgun → html → design-review | Design system building |
| docs | document-generate → document-release | Documentation lifecycle |
| release | review → qa → document-release → ship → land-and-deploy → canary | Production release |
| retro | retro → learn | Weekly retrospective |

## Skill Categories

### Planning (Think → Plan)
- `/office-hours` — YC-style 6 forcing questions
- `/plan-ceo-review` — 4-mode scope review
- `/plan-eng-review` — Architecture, tests, security
- `/plan-design-review` — 10-dimension audit (0-10)
- `/plan-devex-review` — DX plan audit

### Design
- `/design-consultation` — Build design system from scratch
- `/design-shotgun` — 4-6 variants, iterate, converge
- `/design-html` — Production HTML/CSS from mockup
- `/design-review` — Audit + fix UI (10 dimensions)
- `/devex-review` — Live DX testing

### Build & Review
- `/autoplan` — Auto CEO→design→eng pipeline
- `/review` — Staff engineer code review
- `/investigate` — Root cause debugger
- `/codex` — Cross-model second opinion

### Test & Ship
- `/qa` — Browser test + fix + verify
- `/qa-only` — Browser test, report only
- `/ship` — PR + coverage audit
- `/land-and-deploy` — Merge → deploy → verify
- `/canary` — Post-deploy SRE monitoring

### Security & Docs
- `/cso` — OWASP Top 10 + STRIDE
- `/document-release` — Update all docs post-release
- `/document-generate` — Generate missing docs (Diataxis)

### Reflection
- `/retro` — Weekly team retro
- `/learn` — Cross-session learning store

### Power Tools
- `/careful` — Destructive command guard
- `/freeze` — Edit lock (single directory)
- `/guard` — /careful + /freeze
- `/unfreeze` — Release edit lock
- `/spec` — Vague intent → executable spec
- `/diagram` — English → Mermaid + Excalidraw + SVG
- `/make-pdf` — Markdown → publication PDF

## Streaming

WebSocket real-time skill execution:
```javascript
const ws = new WebSocket("ws://localhost:8000/nostack/skills/office-hours/stream");
ws.onopen = () => ws.send(JSON.stringify({ task: "build a daily briefing app" }));
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.type === "done") console.log(msg.result);
  else if (msg.type === "error") console.error(msg.message);
};
```

SSE alternative (no WebSocket needed):
```bash
curl -N "http://localhost:8000/nostack/skills/cso/stream?task=audit+my+codebase"
```

## Testing

```bash
# Run all nostack tests
make nostack-test

# Run full suite
make test
```

## Architecture Notes

- Skills are loaded from `nostack/skills/*.md` persona files
- Registered as `SpecialistAgent` entries in Nexus AI's registry (46 total agents)
- Sprint state is persisted via `save_pref`/`load_pref` to survive restarts
- Background execution uses daemon threads with per-skill timeout (default 5 min)
- Crash handler sets `status=crashed` so failed sprints don't appear as `"running"`
