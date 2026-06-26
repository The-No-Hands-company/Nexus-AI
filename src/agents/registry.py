from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpecialistAgent:
    id: str
    name: str
    icon: str
    description: str
    keywords: tuple[str, ...]
    preferred_providers: tuple[str, ...]
    temperature: float
    tier: str
    system_prompt: str

    def matches(self, task: str) -> int:
        hay = (task or "").lower()
        score = 0
        for kw in self.keywords:
            token = kw.lower().strip()
            if token and token in hay:
                score += 1
        return score


SPECIALIST_AGENTS: tuple[SpecialistAgent, ...] = (
    SpecialistAgent(
        id="architect",
        name="System Architect",
        icon="A",
        description="Designs system architecture and plans.",
        keywords=("architecture", "system design", "scalability", "blueprint"),
        preferred_providers=("groq", "openai"),
        temperature=0.3,
        tier="advanced",
        system_prompt="You are a pragmatic software architect.",
    ),
    SpecialistAgent(
        id="security_auditor",
        name="Security Auditor",
        icon="S",
        description="Finds vulnerabilities and hardening opportunities.",
        keywords=("security", "vulnerability", "xss", "sql injection", "audit", "harden"),
        preferred_providers=("groq", "openai"),
        temperature=0.2,
        tier="advanced",
        system_prompt="You are a security auditor focused on actionable risk reduction.",
    ),
    SpecialistAgent(
        id="debugger",
        name="Debugger",
        icon="D",
        description="Diagnoses and fixes bugs quickly.",
        keywords=("debug", "bug", "traceback", "exception", "fix"),
        preferred_providers=("groq", "openai"),
        temperature=0.2,
        tier="standard",
        system_prompt="You are a debugging specialist.",
    ),
    SpecialistAgent(
        id="data_scientist",
        name="Data Scientist",
        icon="DS",
        description="Builds analyses and ML workflows.",
        keywords=("pandas", "sklearn", "machine learning", "data", "model"),
        preferred_providers=("openai", "groq"),
        temperature=0.4,
        tier="advanced",
        system_prompt="You are a data scientist who explains assumptions clearly.",
    ),
    SpecialistAgent(
        id="ui_ux_designer",
        name="UI UX Designer",
        icon="U",
        description="Improves product usability and interaction design.",
        keywords=("ui", "ux", "layout", "design", "frontend"),
        preferred_providers=("openai", "groq"),
        temperature=0.5,
        tier="standard",
        system_prompt="You are a UI/UX designer with a product mindset.",
    ),
    SpecialistAgent(
        id="documentation_writer",
        name="Documentation Writer",
        icon="W",
        description="Creates concise, useful developer documentation.",
        keywords=("docs", "documentation", "readme", "guide"),
        preferred_providers=("openai", "groq"),
        temperature=0.3,
        tier="standard",
        system_prompt="You write clear, accurate documentation.",
    ),
    SpecialistAgent(
        id="product_manager",
        name="Product Manager",
        icon="PM",
        description="Turns goals into scoped plans and priorities.",
        keywords=("roadmap", "priority", "product", "requirements", "scope"),
        preferred_providers=("openai", "groq"),
        temperature=0.4,
        tier="standard",
        system_prompt="You are a product manager balancing value and risk.",
    ),
    SpecialistAgent(
        id="code_reviewer",
        name="Code Reviewer",
        icon="CR",
        description="Reviews code for correctness, risks, and maintainability.",
        keywords=("review", "code review", "refactor", "quality", "maintainability"),
        preferred_providers=("groq", "openai"),
        temperature=0.2,
        tier="standard",
        system_prompt="You are a strict but constructive code reviewer.",
    ),
    SpecialistAgent(
        id="legal_compliance",
        name="Legal / Compliance Agent",
        icon="LC",
        description="Ensures regulatory compliance and legal review.",
        keywords=("gdpr", "compliance", "legal", "regulation", "policy"),
        preferred_providers=("openai", "groq"),
        temperature=0.2,
        tier="advanced",
        system_prompt="You are a legal and compliance expert focused on regulatory risk reduction.",
    ),
    SpecialistAgent(
        id="devops_infrastructure",
        name="DevOps / Infrastructure Agent",
        icon="DO",
        description="Manages infrastructure, CI/CD, and deployment automation.",
        keywords=("docker", "kubernetes", "ci/cd", "deployment", "infrastructure", "devops"),
        preferred_providers=("groq", "openai"),
        temperature=0.3,
        tier="advanced",
        system_prompt="You are a DevOps engineer focused on reliable infrastructure.",
    ),
    SpecialistAgent(
        id="qa_testing",
        name="QA / Testing Agent",
        icon="QA",
        description="Designs and runs test strategies for software quality.",
        keywords=("test", "qa", "quality", "assert", "coverage", "pytest"),
        preferred_providers=("groq", "openai"),
        temperature=0.3,
        tier="standard",
        system_prompt="You are a QA engineer who writes thorough, maintainable tests.",
    ),
    SpecialistAgent(
        id="marketing_copy",
        name="Marketing / Copy Agent",
        icon="MC",
        description="Creates compelling marketing copy and messaging.",
        keywords=("marketing", "copy", "branding", "messaging", "campaign"),
        preferred_providers=("openai", "groq"),
        temperature=0.6,
        tier="standard",
        system_prompt="You are a marketing copywriter who creates compelling, brand-aligned messaging.",
    ),
    SpecialistAgent(
        id="finance_budget",
        name="Finance / Budget Agent",
        icon="FB",
        description="Analyzes budgets, financial models, and cost optimization.",
        keywords=("budget", "finance", "cost", "roi", "forecast"),
        preferred_providers=("openai", "groq"),
        temperature=0.2,
        tier="advanced",
        system_prompt="You are a financial analyst focused on budget optimization and ROI.",
    ),
    SpecialistAgent(
        id="research_scientist",
        name="Research Scientist",
        icon="RS",
        description="Conducts research analysis and literature review.",
        keywords=("research", "paper", "literature", "experiment", "hypothesis"),
        preferred_providers=("openai", "groq"),
        temperature=0.4,
        tier="advanced",
        system_prompt="You are a research scientist who evaluates evidence rigorously.",
    ),
    SpecialistAgent(
        id="accessibility_auditor",
        name="Accessibility Auditor",
        icon="AA",
        description="Audits applications for accessibility compliance and inclusive design.",
        keywords=("accessibility", "a11y", "wcag", "aria", "inclusive"),
        preferred_providers=("groq", "openai"),
        temperature=0.2,
        tier="standard",
        system_prompt="You are an accessibility auditor focused on WCAG compliance and inclusive design.",
    ),
)


def _to_payload(agent: SpecialistAgent, include_extended: bool = False) -> dict:
    payload = {
        "id": agent.id,
        "name": agent.name,
        "icon": agent.icon,
        "description": agent.description,
        "tier": agent.tier,
    }
    if include_extended:
        payload.update(
            {
                "keywords": list(agent.keywords),
                "preferred_providers": list(agent.preferred_providers),
                "temperature": agent.temperature,
                "system_prompt": agent.system_prompt,
            }
        )
    return payload


def list_agents(include_extended: bool = False) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for agent in _all_agents():
        if agent.id not in seen:
            seen.add(agent.id)
            result.append(_to_payload(agent, include_extended=include_extended))
    return result


def get_specialist(agent_id: str) -> SpecialistAgent | None:
    wanted = (agent_id or "").strip().lower()
    for agent in _all_agents():
        if agent.id == wanted:
            return agent
    return None


def _all_agents():
    yield from SPECIALIST_AGENTS
    try:
        yield from NOSTACK_AGENTS
    except NameError:
        pass


def classify_to_specialist(task: str) -> SpecialistAgent:
    best = None
    best_score = -1
    for agent in _all_agents():
        score = agent.matches(task)
        if score > best_score:
            best = agent
            best_score = score
    if best is None:
        return SPECIALIST_AGENTS[0]

    # Deterministic fallback for coding/debug tasks when keyword scores tie at zero.
    if best_score <= 0:
        task_lower = (task or "").lower()
        if any(token in task_lower for token in ("debug", "bug", "traceback", "fix", "python", "code")):
            return get_specialist("debugger") or best
        return get_specialist("code_reviewer") or best
    return best


# nostack integration
try:
    from nostack.registry import register_nostack_agents, NOSTACK_AGENTS
    register_nostack_agents()
except ImportError:
    pass
