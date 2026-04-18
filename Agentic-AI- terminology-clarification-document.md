# AI Terminology Hierarchy (Modern LLM-Centric View)

This file defines the exact placement of Nexus AI so there is no misunderstanding of what we are building.

## Canonical Hierarchy

Artificial Intelligence (AI)
│
├── 1. AI Field / Discipline
│   (the broad science and engineering domain)
│
├── 2. AI Model / Foundation Model
│   │
│   ├── Base Model (pre-trained weights only)
│   ├── Post-trained / Aligned Model (SFT, RLHF/RLAIF, constitutional alignment)
│   └── Specialized Variants (multimodal, SLMs, reasoning-optimized)
│
├── 3. AI Application / Assistant
│   (model + interface + system prompt + memory + UX)
│   Examples: ChatGPT app, Claude.ai, Grok chat, Perplexity
│
└── 4. AI Agent
    (planner + tools + memory + autonomous execution loop)

## Precise Placement for Nexus AI

Nexus AI spans both levels:

- Level 3 (outside): user-facing AI Assistant application
- Level 4 (inside): full AI Agent runtime engine

In practical terms: Nexus AI is an Agentic AI Assistant.

## Structure for Nexus AI

Artificial Intelligence (AI)
│
├── 3. AI Application / Assistant   <- User-facing layer
│   │   (model + interface + system prompt + memory + UI)
│   │
│   ├── Web UI / PWA experience
│   ├── Persona selection (Assistant, Coder, Researcher, Creative, etc.)
│   ├── Prompt-first workflow: pick persona -> prompt -> done
│   └── Thin, friendly wrapper that hides routing and infrastructure complexity
│
└── 4. AI Agent   <- Core runtime engine inside Nexus AI
    │
    ├── Core components implemented
    │   • Brain/Reasoner: foundation models via multi-provider routing
    │   • Memory: session context + file/repo working memory (+ optional long-term memory)
    │   • Tools/Actions: search, code/file operations, command execution, media/document tools, etc.
    │   • Planner/Orchestrator: explicit plan/clarify flows + complexity-aware execution
    │   • Executor loop: think -> plan -> clarify -> act -> respond
    │
    ├── Agent archetypes matched
    │   • ReAct / Tool-Use Agent
    │   • Autonomous / Long-Running Agent (no-hands execution style)
    │   • Reasoning Agent (decomposition + self-correction behavior)
    │   • Multimodal Agentic Flow (artifacts, docs, image-capable paths)
    │
    └── Product-level construct
        • Agentic Application (full product built from an agent engine + UX shell)

## Why Nexus AI Is Not Only a Level-3 Assistant

- Outside view (what users experience): an easy assistant app.
- Inside view (what actually executes): a routed, tool-using, autonomous agent loop.

Therefore, the most accurate description is:

- Agentic AI Assistant
- Smart-Routing Multi-Provider Agent
- Self-Hosted Sovereign Agentic Application

## Official Terminology for Docs/README

| Preferred term | Why it fits Nexus AI |
| --- | --- |
| AI Agent | Core runtime is an autonomous tool-calling planner/executor loop |
| Agentic AI Assistant | Best user-facing description: assistant UX over agent internals |
| Smart-Routing Multi-Provider Agent | Reflects provider routing, fallback, and complexity-aware model selection |
| Self-Hosted Sovereign Agent | Matches local-first, zero lock-in, provider-agnostic philosophy |
| Agentic Application | Correct product-level category (agent + full interface + workflows) |

## One-Line Classification

Nexus AI is a Level-4 AI Agent delivered through a Level-3 Assistant interface.
