Once Nexus AI is ready for public release, we will publish a comprehensive glossary of terms and definitions in the README and docs. For now, here are personal notes on terminology decisions, hierarchy placement, and future direction for Nexus AI.

---

## AI Hierarchy

The hierarchy flows from the broad AI System → Models (intelligence) → Agent Layer (orchestration and autonomy) → Tasks.

**Important**: the model does **not** use agents. **Agents use models** as their reasoning engine.

```
AI System (the whole product/experience)
│
├── 1. AI Field / Discipline
│   (the broad science and engineering domain)
│
├── 2. Foundation Model(s)   ← the core "brain" (LLM: Grok, GPT, Claude, etc.)
│   ├── Base Model (pre-trained weights only)
│   ├── Post-trained / Aligned Model (SFT, RLHF/RLAIF, constitutional alignment)
│   └── Specialized Variants (multimodal, SLMs, reasoning-optimized)
│
├── 3. AI Application / Assistant
│   (model + interface + system prompt + memory + UX)
│   Examples: ChatGPT app, Claude.ai, Grok chat, Perplexity
│
└── 4. AI Agent / Agentic Layer
    (planner + tools + memory + autonomous execution loop)
    └── Individual Agents or Agentic Workflows
            └── Tasks / Tools / Actions
```

---

## Levels of AI Systems

### 1. Simple LLM Chat (Raw Model)
Direct prompting to the foundation model. One-shot or short conversation responses. No tools, no looping, limited memory. Fast but struggles with complex tasks.

### 2. Tool-Calling / Function Calling
Model can call predefined tools (search, code execution, etc.). Results fed back into the model for continued reasoning. Reactive, usually single loop.

### 3. Single Agent (Agentic Workflow)
Goal-oriented system built around a model. Features: reasoning loop, memory (short + long-term), tool use, planning, self-correction. Keeps iterating until task completion. Common patterns: ReAct, Plan-and-Execute, Reflexion.

### 4. Multi-Agent Systems
Multiple specialized agents working together. Each has roles (Researcher, Writer, Critic, Coder, etc.). Can communicate, delegate, critique. Supervisor/orchestrator coordinates. Patterns: Hierarchical, Sequential, Conversational/Peer-to-peer, Swarm.

### 5. Agent Swarms / Advanced Multi-Agent
Large numbers of lightweight agents. Used for simulation, optimization, massive parallel tasks. Still maturing.

---

## Nexus AI Placement

Nexus AI spans two levels simultaneously:

- **Level 3 (outside)**: user-facing AI Assistant application
- **Level 4 (inside)**: full AI Agent runtime engine

In practical terms: **Nexus AI is an Agentic AI Assistant.**

```
3. AI Application / Assistant   ← User-facing layer
│   (model + interface + system prompt + memory + UI)
│   ├── Web UI / PWA experience
│   ├── Persona selection (Assistant, Coder, Researcher, Creative, etc.)
│   ├── Prompt-first workflow: pick persona → prompt → done
│   └── Thin, friendly wrapper that hides routing and infrastructure complexity
│
└── 4. AI Agent   ← Core runtime engine inside Nexus AI
    ├── Core components
    │   • Brain/Reasoner: foundation models via multi-provider routing
    │   • Memory: session context + file/repo working memory (+ optional long-term memory)
    │   • Tools/Actions: search, code/file operations, command execution, media/document tools
    │   • Planner/Orchestrator: explicit plan/clarify flows + complexity-aware execution
    │   • Executor loop: think → plan → clarify → act → respond
    │
    ├── Agent archetypes matched
    │   • ReAct / Tool-Use Agent
    │   • Autonomous / Long-Running Agent (no-hands execution style)
    │   • Reasoning Agent (decomposition + self-correction behavior)
    │   • Multimodal Agentic Flow (artifacts, docs, image-capable paths)
    │
    └── Product-level construct
        • Agentic Application (full product built from an agent engine + UX shell)
```

---

## Official Terminology

| Preferred term | Why it fits Nexus AI |
|---|---|
| AI Agent | Core runtime is an autonomous tool-calling planner/executor loop |
| Agentic AI Assistant | Best user-facing description: assistant UX over agent internals |
| Smart-Routing Multi-Provider Agent | Reflects provider routing, fallback, and complexity-aware model selection |
| Self-Hosted Sovereign Agent | Matches local-first, zero lock-in, provider-agnostic philosophy |
| Agentic Application | Correct product-level category (agent + full interface + workflows) |

**One-line classification**: Nexus AI is a Level-4 AI Agent delivered through a Level-3 Assistant interface — a product-level Agentic Application with a user-friendly UX shell over a powerful autonomous agent engine.

---

## Popular Frameworks (2026, for reference)

- **LangGraph** (LangChain): Complex stateful workflows, production-ready.
- **CrewAI**: Role-based "crews" of agents.
- **AutoGen** (Microsoft): Conversational multi-agent.
- **OpenAI Swarm**: Lightweight swarms.
- Others: Google ADK, LlamaIndex, Anthropic SDK.

---

## Future Capabilities (post-production-ready)

### Nexus AI Artist (Image Generation)
The AI will be able to generate images as part of its capabilities — a multimodal agentic flow where the agent produces not just text but also visual artifacts in response to user prompts or as part of its execution process. This further solidifies Nexus AI as a cutting-edge Agentic Application.

---

## Architecture Scaffold (Implemented)

`src/architecture/hierarchy.py` defines typed nodes for foundation models, agents, workflows, and the task/tool layer. `GET /architecture/hierarchy` exposes a live, read-only hierarchy snapshot built from the current provider catalog, specialist agent registry, and built-in tool list.

This avoids a disruptive rewrite later by introducing the hierarchy boundary early — you can keep building Nexus AI as usual today, and when deeper model/agent layers are needed, the contract and shape already exist.

### Suggested expansion phases (future)

1. Add persistent storage for hierarchy nodes and links.
2. Add versioned architecture blueprints (draft, active, archived).
3. Add capability-level matching (agent requires model capability set).
4. Add execution policy contracts (cost, latency, risk) per workflow edge.
5. Add simulation/sandbox mode to test new hierarchy graphs before enabling in production.

----


