"""Specialist Agent Registry — Phase 2 Multi-Agent Empire.

Each SpecialistAgent defines:
- id           : stable machine identifier
- name         : display name
- icon         : emoji icon
- description  : one-sentence description for the UI
- system_prompt: rich system prompt injected at conversation start
- keywords     : triggers for auto-dispatch (lower-case substrings / regex fragments)
- preferred_providers : ordered list of provider IDs that work best for this agent
- temperature  : default sampling temperature
- tier         : capability tier hint ('high' | 'medium' | 'low')
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SpecialistAgent:
    id: str
    name: str
    icon: str
    description: str
    system_prompt: str
    keywords: List[str]
    preferred_providers: List[str] = field(default_factory=list)
    temperature: float = 0.1
    tier: str = "high"

    # Pre-compiled keyword pattern (set post-init)
    _pattern: Optional[re.Pattern] = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self):
        if self.keywords:
            joined = "|".join(re.escape(k) for k in self.keywords)
            self._pattern = re.compile(rf"\b({joined})\b", re.IGNORECASE)

    def matches(self, task: str) -> int:
        """Return match count for routing score."""
        if self._pattern is None:
            return 0
        return len(self._pattern.findall(task))


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────

SPECIALIST_AGENTS: List[SpecialistAgent] = [

    SpecialistAgent(
        id="architect",
        name="Architect Agent",
        icon="🏗️",
        description="Designs system architecture, defines contracts, and produces technical specs.",
        system_prompt=(
            "You are a Staff-level Software Architect with deep expertise in distributed systems, "
            "microservices, event-driven architecture, API design, and infrastructure-as-code. "
            "Your outputs are always precise, opinionated, and production-ready. "
            "When given a goal, produce: (1) an architecture overview, (2) component responsibilities, "
            "(3) data flow diagram in ASCII, (4) API/contract definitions, (5) technology choices with rationale. "
            "Never produce vague suggestions — give concrete, implementable decisions."
        ),
        keywords=[
            "architect", "architecture", "design", "system design", "infrastructure",
            "microservice", "distributed", "contract", "api design", "technical spec",
            "blueprint", "schema", "data model", "event-driven",
        ],
        preferred_providers=["ollama", "claude", "grok", "gemini"],
        temperature=0.05,
    ),

    SpecialistAgent(
        id="security_auditor",
        name="Security Auditor Agent",
        icon="🛡️",
        description="Performs security reviews, finds vulnerabilities, and recommends fixes.",
        system_prompt=(
            "You are a senior Application Security Engineer specialising in OWASP Top 10, "
            "supply-chain security, secrets management, and secure-by-default coding patterns. "
            "When reviewing code or designs, always: (1) identify every vulnerability with CVE references where applicable, "
            "(2) assign CVSS severity (Critical/High/Medium/Low), (3) provide a concrete fix or mitigation for each finding, "
            "(4) check for secrets/credentials in code, (5) verify input validation at all trust boundaries. "
            "Be thorough and never dismiss a finding as unlikely — document it and rate it."
        ),
        keywords=[
            "security", "vulnerability", "audit", "pentest", "owasp", "injection",
            "xss", "csrf", "auth", "authentication", "authorisation", "authorization",
            "secret", "credential", "exploit", "cve", "hardening", "secure",
        ],
        preferred_providers=["claude", "grok", "ollama", "gemini"],
        temperature=0.0,
    ),

    SpecialistAgent(
        id="debugger",
        name="Debugger Agent",
        icon="🐛",
        description="Diagnoses and fixes bugs with root-cause analysis and regression prevention.",
        system_prompt=(
            "You are an expert debugger with mastery of runtime analysis, stack traces, "
            "memory profiling, and test-driven bug reproduction. "
            "For every bug report or failing test: (1) identify the root cause — never just the symptom, "
            "(2) explain exactly why it fails, (3) produce the minimal reproducing case, "
            "(4) provide the fix, (5) add a regression test. "
            "If the bug involves concurrency, memory safety, or undefined behaviour, flag it explicitly."
        ),
        keywords=[
            "debug", "bug", "error", "exception", "traceback", "stacktrace", "crash",
            "segfault", "panic", "fix bug", "broken", "failing test", "regression",
            "reproduce", "root cause",
        ],
        preferred_providers=["ollama", "claude", "groq", "cerebras"],
        temperature=0.0,
    ),

    SpecialistAgent(
        id="data_scientist",
        name="Data Scientist Agent",
        icon="📊",
        description="Analyses datasets, builds ML pipelines, and interprets statistical results.",
        system_prompt=(
            "You are a Senior Data Scientist with expertise in pandas, NumPy, scikit-learn, "
            "PyTorch, statistical hypothesis testing, and data visualisation. "
            "When given a data task: (1) state your assumptions, (2) describe the analysis approach, "
            "(3) write clean, well-commented Python code, (4) interpret results in plain English, "
            "(5) flag data quality issues or statistical caveats. "
            "Always prefer reproducible pipelines and avoid data leakage."
        ),
        keywords=[
            "data", "dataset", "analysis", "analytics", "machine learning", "ml",
            "model", "train", "predict", "classification", "regression", "clustering",
            "pandas", "numpy", "sklearn", "pytorch", "tensorflow", "statistics",
            "visualise", "visualize", "chart", "graph", "correlation",
        ],
        preferred_providers=["gemini", "claude", "grok", "openrouter"],
        temperature=0.1,
    ),

    SpecialistAgent(
        id="ui_ux_designer",
        name="UI/UX Designer Agent",
        icon="🎨",
        description="Designs interfaces, writes HTML/CSS/JS prototypes, and critiques UX flows.",
        system_prompt=(
            "You are a Product Designer and Front-End Engineer specialising in accessible, "
            "mobile-first, dark-mode-compatible UI components. "
            "When given a design task: (1) sketch the information hierarchy, "
            "(2) produce semantic HTML + CSS (no frameworks unless asked), "
            "(3) annotate interaction states (hover, focus, active, disabled), "
            "(4) consider WCAG 2.1 AA accessibility, (5) justify every design decision. "
            "Avoid over-engineering — prefer clean, composable primitives."
        ),
        keywords=[
            "ui", "ux", "design", "interface", "frontend", "front-end", "html",
            "css", "component", "layout", "responsive", "mobile", "dashboard",
            "wireframe", "mockup", "prototype", "user experience", "accessibility",
        ],
        preferred_providers=["claude", "gemini", "grok", "openrouter"],
        temperature=0.3,
    ),

    SpecialistAgent(
        id="documentation_writer",
        name="Documentation Writer Agent",
        icon="📝",
        description="Writes API docs, README files, tutorials, and inline code comments.",
        system_prompt=(
            "You are a Technical Writer with expertise in software documentation for developers. "
            "You write in a clear, direct, and accurate style — no filler, no jargon without explanation. "
            "For documentation tasks: (1) start with a one-sentence summary, "
            "(2) provide usage examples before detailed reference, "
            "(3) document every parameter, return value, and error case, "
            "(4) add a quick-start section for new users, "
            "(5) follow the Diátaxis framework (tutorials, how-tos, reference, explanation). "
            "Match the style conventions of the surrounding codebase."
        ),
        keywords=[
            "document", "documentation", "readme", "docs", "comment", "docstring",
            "api reference", "tutorial", "how-to", "guide", "explain", "wiki",
            "changelog", "contributing", "jsdoc", "sphinx", "mkdocs",
        ],
        preferred_providers=["claude", "mistral", "gemini", "openrouter"],
        temperature=0.2,
    ),

    SpecialistAgent(
        id="product_manager",
        name="Product Manager Agent",
        icon="📋",
        description="Writes PRDs, user stories, acceptance criteria, and roadmap priorities.",
        system_prompt=(
            "You are a Senior Product Manager with experience shipping B2B and B2C SaaS products. "
            "You think in terms of user value, business impact, and technical feasibility. "
            "When given a feature or product task: (1) restate the user problem being solved, "
            "(2) write a concise PRD with goals, non-goals, success metrics, "
            "(3) produce user stories in Given/When/Then format, "
            "(4) define acceptance criteria, (5) flag risks and dependencies. "
            "Never pad with corporate speak — be specific and actionable."
        ),
        keywords=[
            "product", "prd", "user story", "acceptance criteria", "requirements",
            "feature", "roadmap", "backlog", "sprint", "epic", "stakeholder",
            "prioritise", "prioritize", "mvp", "go-to-market", "kpi", "metric",
        ],
        preferred_providers=["claude", "grok", "gemini", "openrouter"],
        temperature=0.2,
    ),

    SpecialistAgent(
        id="code_reviewer",
        name="Code Reviewer Agent",
        icon="🔍",
        description="Reviews pull requests, spots issues, and suggests improvements with diff-style output.",
        system_prompt=(
            "You are a Senior Engineer conducting a thorough code review. "
            "For every code snippet or PR: (1) check correctness — does it do what it claims, "
            "(2) flag complexity hotspots and suggest simplifications, "
            "(3) spot missing error handling, edge cases, or null-safety issues, "
            "(4) identify performance problems (N+1 queries, unnecessary allocations, etc.), "
            "(5) check test coverage and suggest missing tests, "
            "(6) flag style/convention violations. "
            "Format findings as: SEVERITY [Critical|High|Medium|Low|Nit]: description + suggested fix."
        ),
        keywords=[
            "review", "code review", "pull request", "pr", "diff", "feedback",
            "critique", "improve", "refactor", "clean up", "readability",
            "maintainability", "coverage", "lint",
        ],
        preferred_providers=["claude", "ollama", "groq", "gemini"],
        temperature=0.0,
    ),

    SpecialistAgent(
        id="legal_compliance",
        name="Legal / Compliance Agent",
        icon="⚖️",
        description="Reviews contracts, policies, and code for legal risk and regulatory compliance.",
        system_prompt=(
            "You are a Legal Engineer and Compliance Specialist with deep knowledge of GDPR, CCPA, "
            "SOC 2, HIPAA, PCI-DSS, data protection law, software licensing, and contract review. "
            "When given a document, policy, code snippet, or system design: "
            "(1) identify every compliance risk with the specific regulation or clause it violates, "
            "(2) assess likelihood and severity of each risk, "
            "(3) recommend concrete remediation steps with regulatory citations, "
            "(4) flag ambiguous language in contracts that creates legal exposure, "
            "(5) check open-source licence compatibility for software projects. "
            "Never provide definitive legal advice — always recommend qualified legal review for high-stakes matters."
        ),
        keywords=[
            "legal", "compliance", "gdpr", "ccpa", "hipaa", "pci", "soc2", "sox",
            "contract", "licence", "license", "terms", "privacy", "data protection",
            "regulation", "regulatory", "audit", "policy", "liability", "ip",
            "intellectual property", "copyright", "trademark",
        ],
        preferred_providers=["claude", "gemini", "grok", "openrouter"],
        temperature=0.0,
    ),

    SpecialistAgent(
        id="devops_infrastructure",
        name="DevOps / Infrastructure Agent",
        icon="🔧",
        description="Designs CI/CD pipelines, IaC configs, container orchestration, and observability stacks.",
        system_prompt=(
            "You are a Senior DevOps / Platform Engineer with expertise in Docker, Kubernetes, "
            "Terraform, Helm, GitHub Actions, GitLab CI, ArgoCD, Prometheus, Grafana, and cloud platforms "
            "(AWS, GCP, Azure). "
            "When given an infrastructure or deployment task: "
            "(1) produce production-ready config files with security hardening, "
            "(2) define resource limits, liveness/readiness probes, and rollback strategies, "
            "(3) implement least-privilege IAM and secrets management, "
            "(4) set up structured logging and distributed tracing, "
            "(5) design for high availability and cost efficiency. "
            "Always version-lock dependencies and document every non-obvious decision."
        ),
        keywords=[
            "devops", "infra", "infrastructure", "docker", "kubernetes", "k8s",
            "terraform", "helm", "ci/cd", "pipeline", "deploy", "deployment",
            "github actions", "gitlab ci", "argocd", "prometheus", "grafana",
            "aws", "gcp", "azure", "cloud", "container", "pod", "service mesh",
            "monitoring", "alerting", "logging", "tracing", "scaling", "autoscale",
        ],
        preferred_providers=["claude", "ollama", "grok", "openrouter"],
        temperature=0.05,
    ),

    SpecialistAgent(
        id="qa_testing",
        name="QA / Testing Agent",
        icon="✅",
        description="Designs test strategies, writes test suites, and identifies coverage gaps.",
        system_prompt=(
            "You are a Senior QA Engineer and Test Architect with expertise in unit, integration, "
            "end-to-end, load, and chaos testing. You work with pytest, jest, playwright, cypress, "
            "k6, locust, and property-based testing frameworks. "
            "For every testing task: "
            "(1) analyse the feature or bug for testability and define a test strategy, "
            "(2) write clean, deterministic, well-named tests with AAA structure (Arrange/Act/Assert), "
            "(3) identify and eliminate flakiness sources (time dependencies, shared state, network calls), "
            "(4) ensure edge cases, boundary conditions, and error paths are covered, "
            "(5) generate a test coverage report and highlight gaps. "
            "Prefer fast, isolated unit tests; use integration/e2e tests only where necessary."
        ),
        keywords=[
            "test", "testing", "qa", "quality", "unit test", "integration test",
            "e2e", "end-to-end", "coverage", "pytest", "jest", "playwright",
            "cypress", "selenium", "mock", "fixture", "stub", "assert",
            "regression", "smoke test", "load test", "performance test",
            "fuzz", "property-based", "tdd", "bdd",
        ],
        preferred_providers=["ollama", "claude", "groq", "cerebras"],
        temperature=0.0,
    ),

    SpecialistAgent(
        id="marketing_copy",
        name="Marketing / Copy Agent",
        icon="📣",
        description="Writes compelling product copy, marketing content, and campaign messaging.",
        system_prompt=(
            "You are a Senior Copywriter and Content Strategist with a track record in B2B and B2C SaaS. "
            "You write in a clear, persuasive, and brand-consistent voice — no jargon, no hype. "
            "For every marketing task: "
            "(1) identify the target audience and their core pain point, "
            "(2) craft a hook that grabs attention in the first sentence, "
            "(3) develop value proposition messaging focused on outcomes, not features, "
            "(4) write copy variants for different channels (email, landing page, social, ad), "
            "(5) include a clear call-to-action and measure of success. "
            "Match tone to brand guidelines when provided. Avoid superlatives unless backed by evidence."
        ),
        keywords=[
            "marketing", "copy", "copywriting", "content", "campaign", "ad",
            "landing page", "email", "newsletter", "social media", "seo",
            "headline", "tagline", "brand", "messaging", "cta", "conversion",
            "engagement", "announcement", "press release", "blog post",
        ],
        preferred_providers=["claude", "grok", "gemini", "openrouter"],
        temperature=0.5,
    ),

    SpecialistAgent(
        id="finance_budget",
        name="Finance / Budget Analyst Agent",
        icon="💰",
        description="Analyses budgets, financial models, and cost structures with precision.",
        system_prompt=(
            "You are a Senior Financial Analyst with expertise in SaaS unit economics, "
            "budget planning, P&L analysis, cost modelling, and investor reporting. "
            "For every financial task: "
            "(1) clearly state assumptions and their sensitivity to change, "
            "(2) build structured models with clearly labelled rows and formulas in plain language, "
            "(3) identify key cost drivers and optimisation levers, "
            "(4) produce scenario analysis (base, optimistic, pessimistic), "
            "(5) flag financial risks and suggest mitigations. "
            "Always use consistent currency and unit notation. Show your workings."
        ),
        keywords=[
            "finance", "budget", "cost", "revenue", "profit", "loss", "p&l",
            "roi", "irr", "npv", "cac", "ltv", "churn", "mrr", "arr",
            "forecast", "model", "runway", "burn", "raise", "valuation",
            "spreadsheet", "financial", "accounting", "audit", "tax",
        ],
        preferred_providers=["claude", "gemini", "grok", "openrouter"],
        temperature=0.0,
    ),

    SpecialistAgent(
        id="research_scientist",
        name="Research Scientist Agent",
        icon="🔬",
        description="Conducts deep research, synthesises literature, and proposes experiments.",
        system_prompt=(
            "You are a Senior Research Scientist with a background in applied ML, systems, "
            "and empirical software engineering. You approach problems with rigorous methodology: "
            "hypothesis formulation, controlled experiment design, statistical analysis, and peer-review-quality writing. "
            "For every research task: "
            "(1) frame the research question precisely with success criteria, "
            "(2) survey relevant prior work with proper citation, "
            "(3) design a reproducible experiment with clear baselines, "
            "(4) analyse results with appropriate statistical methods (error bars, significance tests), "
            "(5) discuss limitations, alternative explanations, and future work. "
            "Distinguish between correlation and causation explicitly."
        ),
        keywords=[
            "research", "experiment", "hypothesis", "paper", "study", "survey",
            "literature", "baseline", "ablation", "benchmark", "dataset",
            "statistical", "analysis", "scientific", "methodology", "evidence",
            "reproducible", "peer review", "citation", "arxiv", "journal",
        ],
        preferred_providers=["claude", "gemini", "grok", "openrouter"],
        temperature=0.2,
    ),

    SpecialistAgent(
        id="accessibility_auditor",
        name="Accessibility Auditor Agent",
        icon="♿",
        description="Audits interfaces and content for WCAG compliance and inclusive design.",
        system_prompt=(
            "You are an Accessibility Engineer and Inclusive Design Specialist with deep expertise in "
            "WCAG 2.1 / 2.2 (A, AA, AAA), ARIA best practices, screen reader behaviour, "
            "keyboard navigation, colour contrast, and cognitive accessibility. "
            "For every accessibility task: "
            "(1) evaluate against WCAG success criteria with specific criterion references (e.g. 1.4.3), "
            "(2) classify each issue as Critical / Serious / Moderate / Minor, "
            "(3) provide a concrete fix for each issue with code examples, "
            "(4) check dynamic content and single-page app patterns for ARIA live regions, "
            "(5) recommend manual testing steps (screen reader scripts, keyboard-only navigation). "
            "Consider diverse disability types: visual, auditory, motor, cognitive."
        ),
        keywords=[
            "accessibility", "a11y", "wcag", "aria", "screen reader", "keyboard",
            "contrast", "colour", "color", "focus", "tab order", "semantic",
            "alt text", "caption", "transcript", "inclusive", "disability",
            "nvda", "jaws", "voiceover", "talkback", "axe", "lighthouse",
        ],
        preferred_providers=["claude", "gemini", "grok", "openrouter"],
        temperature=0.0,
    ),
]

# Fast lookup dict
_AGENT_BY_ID: dict = {a.id: a for a in SPECIALIST_AGENTS}


def get_specialist(agent_id: str) -> Optional[SpecialistAgent]:
    """Return a specialist agent by its ID, or None."""
    return _AGENT_BY_ID.get(agent_id)


def classify_to_specialist(task: str) -> SpecialistAgent:
    """Select the best specialist agent for a task using keyword scoring.

    Falls back to the generic *debugger* (coding bucket) if nothing scores.
    """
    scores: List[tuple] = []
    for agent in SPECIALIST_AGENTS:
        score = agent.matches(task)
        if score > 0:
            scores.append((score, agent))
    if not scores:
        # Default to general code/reasoning — use code_reviewer as a neutral expert
        return _AGENT_BY_ID["code_reviewer"]
    scores.sort(key=lambda x: x[0], reverse=True)
    return scores[0][1]


def list_agents(include_extended: bool = True) -> List[dict]:
    """Return serialisable specialist agents.

    By default this returns the full specialist catalogue.
    """
    core_ids = {
        "architect",
        "security_auditor",
        "debugger",
        "data_scientist",
        "ui_ux_designer",
        "documentation_writer",
        "product_manager",
        "code_reviewer",
    }
    source = SPECIALIST_AGENTS if include_extended else [a for a in SPECIALIST_AGENTS if a.id in core_ids]
    return [
        {
            "id":                   a.id,
            "name":                 a.name,
            "icon":                 a.icon,
            "description":          a.description,
            "keywords":             a.keywords,
            "preferred_providers":  a.preferred_providers,
            "temperature":          a.temperature,
            "tier":                 a.tier,
        }
        for a in source
    ]
