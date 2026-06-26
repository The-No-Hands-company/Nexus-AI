from __future__ import annotations

import os as _os
from collections.abc import MutableSequence
from pathlib import Path as _Path

from src.agents.registry import SpecialistAgent

_SKILLS_DIR = _Path(__file__).resolve().parent / "skills"


def _skill_prompt(filename: str) -> str:
    return f"[skill from nostack/skills/{filename}]"


def load_nostack_prompt(agent_id: str) -> str:
    skill_name = agent_id.replace("nostack-", "", 1)
    skill_path = _SKILLS_DIR / f"{skill_name}.md"
    if not skill_path.is_file():
        raise FileNotFoundError(f"Skill file not found: {skill_path}")
    return skill_path.read_text(encoding="utf-8")


NOSTACK_AGENTS: tuple[SpecialistAgent, ...] = (
    SpecialistAgent(
        id="nostack-office-hours",
        name="Office Hours",
        icon="OH",
        description="YC-style product interrogation with 6 forcing questions. Start here before writing code.",
        keywords=("plan", "product", "idea", "design", "scope", "clarify", "interrogate"),
        preferred_providers=(),
        temperature=0.7,
        tier="advanced",
        system_prompt=_skill_prompt("office-hours.md"),
    ),
    SpecialistAgent(
        id="nostack-autoplan",
        name="Review Pipeline",
        icon="AP",
        description="Automated multi-stage plan review: CEO, design, engineering. Only true judgment calls surface to humans.",
        keywords=("autoplan", "pipeline", "review", "plan", "automated", "ceo", "design", "engineering"),
        preferred_providers=(),
        temperature=0.3,
        tier="advanced",
        system_prompt=_skill_prompt("autoplan.md"),
    ),
    SpecialistAgent(
        id="nostack-plan-ceo-review",
        name="CEO / Founder Review",
        icon="CEO",
        description="Makes hard decisions about scope, ambition, and direction. Operates in four modes: extend, scope-creep, trim, pivot.",
        keywords=("ceo", "founder", "scope", "ambition", "direction", "pivot", "plan", "strategy"),
        preferred_providers=(),
        temperature=0.4,
        tier="advanced",
        system_prompt=_skill_prompt("plan-ceo-review.md"),
    ),
    SpecialistAgent(
        id="nostack-plan-eng-review",
        name="Engineering Manager",
        icon="EM",
        description="Reviews design docs for technical feasibility, architecture, testing, and safe shipping. Locks in the architecture.",
        keywords=("engineering", "manager", "architecture", "feasibility", "testing", "plan", "tech"),
        preferred_providers=(),
        temperature=0.3,
        tier="advanced",
        system_prompt=_skill_prompt("plan-eng-review.md"),
    ),
    SpecialistAgent(
        id="nostack-plan-design-review",
        name="Senior Designer",
        icon="SD",
        description="Audits design plans across 10 dimensions with 0-10 scoring, specific improvements, and AI slop detection.",
        keywords=("design", "audit", "ui", "ux", "review", "plan", "designer", "slop"),
        preferred_providers=(),
        temperature=0.5,
        tier="standard",
        system_prompt=_skill_prompt("plan-design-review.md"),
    ),
    SpecialistAgent(
        id="nostack-plan-devex-review",
        name="DX Reviewer",
        icon="DXP",
        description="Audits plans for developer experience: onboarding speed, dev loop, tooling, API ergonomics, and error clarity.",
        keywords=("devex", "dx", "developer", "experience", "plan", "audit", "onboarding", "tooling"),
        preferred_providers=(),
        temperature=0.3,
        tier="standard",
        system_prompt=_skill_prompt("plan-devex-review.md"),
    ),
    SpecialistAgent(
        id="nostack-design-consultation",
        name="Design Partner",
        icon="DC",
        description="Builds complete cohesive design systems from scratch — visual language, tokens, principles, and production artifacts.",
        keywords=("design", "system", "consultation", "tokens", "visual", "language", "partner"),
        preferred_providers=(),
        temperature=0.5,
        tier="advanced",
        system_prompt=_skill_prompt("design-consultation.md"),
    ),
    SpecialistAgent(
        id="nostack-design-shotgun",
        name="Design Explorer",
        icon="DE",
        description="Generates 4-6 design variants fast. Explores surprising directions and converges toward a loved visual identity.",
        keywords=("design", "explore", "variant", "shotgun", "visual", "iterate", "identity", "creative"),
        preferred_providers=(),
        temperature=0.5,
        tier="standard",
        system_prompt=_skill_prompt("design-shotgun.md"),
    ),
    SpecialistAgent(
        id="nostack-design-html",
        name="Design Engineer",
        icon="DH",
        description="Bridges visual design to production HTML/CSS. Works at every viewport, passes accessibility checks, ships directly.",
        keywords=("html", "css", "design", "engineer", "production", "viewport", "accessibility", "frontend"),
        preferred_providers=(),
        temperature=0.4,
        tier="standard",
        system_prompt=_skill_prompt("design-html.md"),
    ),
    SpecialistAgent(
        id="nostack-design-review",
        name="Designer Who Codes",
        icon="DR",
        description="Audits UI implementation, rates it, and fixes problems directly. Sharp taste, zero tolerance for AI slop.",
        keywords=("design", "review", "ui", "audit", "fix", "implementation", "slop"),
        preferred_providers=(),
        temperature=0.4,
        tier="standard",
        system_prompt=_skill_prompt("design-review.md"),
    ),
    SpecialistAgent(
        id="nostack-review",
        name="Staff Engineer",
        icon="CR",
        description="Rigorous code review — reads every changed line, holds the production bar, uncompromising on correctness and security.",
        keywords=("review", "code", "engineer", "staff", "production", "correctness", "security", "approval"),
        preferred_providers=(),
        temperature=0.2,
        tier="advanced",
        system_prompt=_skill_prompt("review.md"),
    ),
    SpecialistAgent(
        id="nostack-investigate",
        name="Root-Cause Debugger",
        icon="DB",
        description="Finds root cause before any fix. Evidence-driven, methodical, no guessing. Never touches code without proof.",
        keywords=("debug", "investigate", "root", "cause", "trace", "evidence", "bug"),
        preferred_providers=(),
        temperature=0.2,
        tier="standard",
        system_prompt=_skill_prompt("investigate.md"),
    ),
    SpecialistAgent(
        id="nostack-devex-review",
        name="Developer Experience Tester",
        icon="DX",
        description="Live DX audit — clones the repo, times onboarding, rates tooling, tests error messages, and scores the dev experience.",
        keywords=("devex", "dx", "developer", "experience", "audit", "onboarding", "tooling", "ergonomics"),
        preferred_providers=(),
        temperature=0.3,
        tier="standard",
        system_prompt=_skill_prompt("devex-review.md"),
    ),
    SpecialistAgent(
        id="nostack-qa",
        name="QA Lead",
        icon="QA",
        description="Tests like a real user in a real browser — find, fix, and verify in a tight reproduce-fix-regression loop.",
        keywords=("qa", "test", "browser", "fix", "verify", "regression", "quality", "reproduce"),
        preferred_providers=(),
        temperature=0.3,
        tier="standard",
        system_prompt=_skill_prompt("qa.md"),
    ),
    SpecialistAgent(
        id="nostack-qa-only",
        name="QA Reporter",
        icon="QR",
        description="Thorough browser testing — documents every bug precisely enough to file as a GitHub issue. Changes nothing.",
        keywords=("qa", "report", "browser", "test", "bug", "report", "observe", "document"),
        preferred_providers=(),
        temperature=0.3,
        tier="standard",
        system_prompt=_skill_prompt("qa-only.md"),
    ),
    SpecialistAgent(
        id="nostack-ship",
        name="Release Engineer",
        icon="RE",
        description="Turns working changes into clean, well-tested, reviewable PRs. Never ships untested code. Tests pass or no ship.",
        keywords=("ship", "release", "pr", "pull", "request", "test", "coverage", "deploy", "merge"),
        preferred_providers=(),
        temperature=0.3,
        tier="standard",
        system_prompt=_skill_prompt("ship.md"),
    ),
    SpecialistAgent(
        id="nostack-land-and-deploy",
        name="Deployment Engineer",
        icon="LD",
        description="Owns the final mile — merges, deploys, and proves healthy in production. Rolls back fast if anything regresses.",
        keywords=("land", "deploy", "merge", "production", "verify", "rollback", "release", "healthy"),
        preferred_providers=(),
        temperature=0.3,
        tier="standard",
        system_prompt=_skill_prompt("land-and-deploy.md"),
    ),
    SpecialistAgent(
        id="nostack-canary",
        name="Site Reliability Engineer",
        icon="SR",
        description="Post-deploy monitoring loop — watches freshly shipped builds, catches regressions, pulls the cord if thresholds breach.",
        keywords=("canary", "sre", "monitor", "deploy", "regression", "alert", "rollback", "reliability"),
        preferred_providers=(),
        temperature=0.2,
        tier="advanced",
        system_prompt=_skill_prompt("canary.md"),
    ),
    SpecialistAgent(
        id="nostack-cso",
        name="Chief Security Officer",
        icon="CSO",
        description="Structured OWASP Top 10 and STRIDE security audit. Only high-confidence (8/10+), actionable findings.",
        keywords=("cso", "security", "owasp", "stride", "audit", "vulnerability", "threat", "confidence"),
        preferred_providers=(),
        temperature=0.2,
        tier="advanced",
        system_prompt=_skill_prompt("cso.md"),
    ),
    SpecialistAgent(
        id="nostack-document-release",
        name="Technical Writer",
        icon="TW",
        description="Updates all project docs post-release. No stale docs — everything matches the current state. Full coverage map.",
        keywords=("documentation", "release", "docs", "writer", "update", "coverage", "stale"),
        preferred_providers=(),
        temperature=0.3,
        tier="standard",
        system_prompt=_skill_prompt("document-release.md"),
    ),
    SpecialistAgent(
        id="nostack-document-generate",
        name="Documentation Author",
        icon="DA",
        description="Creates clear, accurate documentation from scratch following Diataxis framework. Every code example runs verbatim.",
        keywords=("documentation", "generate", "docs", "author", "diataxis", "create", "write"),
        preferred_providers=(),
        temperature=0.3,
        tier="standard",
        system_prompt=_skill_prompt("document-generate.md"),
    ),
    SpecialistAgent(
        id="nostack-retro",
        name="Engineering Manager",
        icon="RET",
        description="Data-driven weekly retrospective from git history. Surfaces patterns, celebrates shipping, unblocks the blocked.",
        keywords=("retro", "retrospective", "weekly", "git", "history", "patterns", "team", "manager"),
        preferred_providers=(),
        temperature=0.4,
        tier="standard",
        system_prompt=_skill_prompt("retro.md"),
    ),
    SpecialistAgent(
        id="nostack-careful",
        name="Safety Guard",
        icon="SG",
        description="Blocks destructive commands — requires explicit user confirmation. Paranoid by design. No shortcuts, no bypasses.",
        keywords=("careful", "safety", "guard", "destructive", "confirm", "command", "rm", "delete", "force"),
        preferred_providers=(),
        temperature=0.2,
        tier="standard",
        system_prompt=_skill_prompt("careful.md"),
    ),
    SpecialistAgent(
        id="nostack-freeze",
        name="Filesystem Gate",
        icon="FG",
        description="Locks down the workspace — only a user-defined freeze zone is writable. Everything else is read-only. Zero exceptions.",
        keywords=("freeze", "lock", "filesystem", "gate", "readonly", "restrict", "edit", "directory"),
        preferred_providers=(),
        temperature=0.2,
        tier="standard",
        system_prompt=_skill_prompt("freeze.md"),
    ),
    SpecialistAgent(
        id="nostack-guard",
        name="Maximum Safety Override",
        icon="MS",
        description="Activates /careful and /freeze simultaneously. Both guardrails locked together — maximum safety for production work.",
        keywords=("guard", "safety", "careful", "freeze", "both", "maximum", "override", "production"),
        preferred_providers=(),
        temperature=0.2,
        tier="standard",
        system_prompt=_skill_prompt("guard.md"),
    ),
    SpecialistAgent(
        id="nostack-unfreeze",
        name="Lock Release Operator",
        icon="LR",
        description="Removes filesystem edit lock, restores full access, and produces audit trail of everything that happened during the lock.",
        keywords=("unfreeze", "release", "lock", "filesystem", "restore", "audit", "remove"),
        preferred_providers=(),
        temperature=0.2,
        tier="standard",
        system_prompt=_skill_prompt("unfreeze.md"),
    ),
    SpecialistAgent(
        id="nostack-codex",
        name="Independent Auditor",
        icon="IA",
        description="Second-opinion code review from a different reasoning model. Cross-validates /review findings. Independence is the value.",
        keywords=("codex", "audit", "second", "opinion", "cross", "validate", "independent", "review", "model"),
        preferred_providers=(),
        temperature=0.2,
        tier="advanced",
        system_prompt=_skill_prompt("codex.md"),
    ),
    SpecialistAgent(
        id="nostack-diagram",
        name="Technical Illustrator",
        icon="TI",
        description="Converts natural language to Mermaid, Excalidraw JSON, and SVG diagrams. Production-quality, zero network, offline rendering.",
        keywords=("diagram", "illustrator", "mermaid", "excalidraw", "svg", "visual", "render"),
        preferred_providers=(),
        temperature=0.4,
        tier="standard",
        system_prompt=_skill_prompt("diagram.md"),
    ),
    SpecialistAgent(
        id="nostack-make-pdf",
        name="Document Publisher",
        icon="PUB",
        description="Transforms markdown to publication-quality PDF, HTML, or DOCX. Handles diagrams, covers, TOC. Investor-grade output.",
        keywords=("pdf", "publish", "document", "markdown", "html", "docx", "export", "generate"),
        preferred_providers=(),
        temperature=0.3,
        tier="standard",
        system_prompt=_skill_prompt("make-pdf.md"),
    ),
    SpecialistAgent(
        id="nostack-learn",
        name="Knowledge Manager",
        icon="KM",
        description="Captures patterns, pitfalls, and preferences across sessions. Compounds institutional memory so the agent gets smarter every time.",
        keywords=("learn", "knowledge", "memory", "session", "patterns", "lessons", "manager", "institutional"),
        preferred_providers=(),
        temperature=0.3,
        tier="standard",
        system_prompt=_skill_prompt("learn.md"),
    ),
    SpecialistAgent(
        id="nostack-spec",
        name="Spec Author",
        icon="SA",
        description="Turns vague intent into precise executable specs — API contracts, data models, state machines, and acceptance criteria.",
        keywords=("spec", "specification", "author", "api", "contract", "data", "model", "state", "machine"),
        preferred_providers=(),
        temperature=0.3,
        tier="standard",
        system_prompt=_skill_prompt("spec.md"),
    ),
)


class NostackSkill:
    """A discovered nostack skill from the skills directory."""
    def __init__(self, name: str, role: str, description: str, system_prompt: str):
        self.name = name
        self.role = role
        self.description = description
        self.system_prompt = system_prompt


def discover_skills() -> list[NostackSkill]:
    """Parse all skill files and return NostackSkill objects."""
    skills: list[NostackSkill] = []
    if not _SKILLS_DIR.is_dir():
        return skills
    for skill_file in sorted(_SKILLS_DIR.glob("*.md")):
        name = skill_file.stem
        content = skill_file.read_text(encoding="utf-8")
        role = ""
        description = ""
        for line in content.split("\n"):
            if line.startswith("## Role:") or line.startswith("## Role "):
                role = line.split(":", 1)[1].strip() if ":" in line else ""
            if role and description:
                break
        description = (
            f"{role} specialist. "
            f"Load via /nostack-{name} or invoke as specialist agent."
        )
        skills.append(NostackSkill(
            name=name,
            role=role or name.replace("-", " ").title(),
            description=description,
            system_prompt=content,
        ))
    return skills


def get_skill(name: str) -> NostackSkill | None:
    """Get a single skill by name."""
    for skill in discover_skills():
        if skill.name == name:
            return skill
    return None


def register_all() -> int:
    """Register all nostack agents into the Nexus AI specialist registry.
    Returns the number of agents registered."""
    count = 0
    try:
        register_nostack_agents()
        import src.agents.registry as _reg
        count = len(NOSTACK_AGENTS)
    except Exception:
        pass
    return count


def list_skill_names() -> list[str]:
    """Return all nostack skill names."""
    return sorted([a.id.replace("nostack-", "", 1) for a in NOSTACK_AGENTS])


def get_skill_prompt(skill_name: str) -> str | None:
    """Get the full system prompt for a nostack skill by name."""
    skill_path = _SKILLS_DIR / f"{skill_name}.md"
    if not skill_path.is_file():
        return None
    return skill_path.read_text(encoding="utf-8")


def get_skill_agent(skill_name: str) -> SpecialistAgent | None:
    """Get the SpecialistAgent for a nostack skill."""
    target_id = f"nostack-{skill_name}"
    for agent in NOSTACK_AGENTS:
        if agent.id == target_id:
            return agent
    return None


def run_skill(skill_name: str, task: str = "", history: list | None = None,
              provider: str = "", model: str = "") -> dict:
    """Run a nostack skill against the Nexus AI agent pipeline.

    Loads the skill persona, prepends it as a system prompt, and passes
    the task through the standard agent execution flow.

    Returns:
        dict with keys: result, provider, model, history, skill_name
    """
    prompt = get_skill_prompt(skill_name)
    if prompt is None:
        return {"error": f"Skill not found: {skill_name}", "available": list_skill_names()}

    agent = get_skill_agent(skill_name)
    system_prompt = agent.system_prompt if agent else prompt

    # Build messages with skill system prompt
    messages = [{"role": "system", "content": system_prompt[:8000]}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": task or f"Run the /{skill_name} skill on the current project."})

    try:
        from src.agent import run_agent_task
        result = run_agent_task(task or f"/{skill_name}", history=messages)
        result["skill_name"] = skill_name
        return result
    except Exception as exc:
        return {"error": str(exc), "skill_name": skill_name, "result": ""}


def register_nostack_agents() -> None:
    import src.agents.registry as _reg

    if not isinstance(_reg.SPECIALIST_AGENTS, MutableSequence):
        _agents = list(_reg.SPECIALIST_AGENTS)
    else:
        _agents = _reg.SPECIALIST_AGENTS

    existing_ids = {a.id for a in _agents}
    for agent in NOSTACK_AGENTS:
        if agent.id not in existing_ids:
            _agents.append(agent)
            existing_ids.add(agent.id)

    _reg.SPECIALIST_AGENTS = tuple(_agents)
