# Nexus-AI Competitor L0/L1 Seed Catalog (2026 Q2)

Purpose: seed L0/L1 roadmap items from major competitor capabilities and announcements, then map only high-value L1 items into L2 engineering backlog.

Scope:

- Competitor signal sources: OpenAI, Anthropic, Google/Gemini, xAI/Grok, Microsoft Copilot.
- Layer: L0 and L1 only (per layered feature model).
- Mapping output: `docs/registry/l1_to_l2_high_value_backlog_2026Q2.csv`.

## Source Notes

- Signal extraction used publicly accessible pages and announcements.
- Some pages are dynamic and may change over time.
- Meta AI public page was blocked by cookie consent in this environment and is not used as a primary source for this seed.

Primary source URLs:

- OpenAI Operator, GPT-5, and product/news index:
  - [OpenAI Operator](https://openai.com/index/introducing-operator/)
  - [GPT-5](https://openai.com/gpt-5/)
  - [GPT-5.3-Codex](https://openai.com/index/introducing-gpt-5-3-codex/) (agentic coding, pay-as-you-go, Apr 2026)
  - [OpenAI Index](https://openai.com/index/)
- Anthropic newsroom and Claude announcements:
  - [Anthropic Newsroom](https://www.anthropic.com/news)
  - [Claude Sonnet 4.6](https://www.anthropic.com/news/claude-sonnet-4-6) (Feb 17, 2026 — coding, computer use, long-context, agent planning)
  - [Claude Opus 4.6](https://www.anthropic.com/news/claude-opus-4-6) (Feb 5, 2026 — agentic coding, computer use, tool use, agent teams)
- Google Gemini and AI updates:
  - [Gemini Technology Page](https://deepmind.google/technologies/gemini/)
  - [Google Gemini Product Updates](https://blog.google/products/gemini/)
  - [Google AI Updates](https://blog.google/technology/ai/)
- xAI blog/news:
  - [xAI Blog](https://x.ai/blog)
- Microsoft Copilot blog:
  - [Microsoft Copilot Blog](https://www.microsoft.com/en-us/microsoft-copilot/blog/)

## L0 Seed Catalog

1. Autonomous Task Execution and Browser/Computer Use
2. Agentic Coding and Dev Workflow Automation
3. Native Multimodality (image, audio, video, docs)
4. Tool Calling and External Action Reliability
5. Memory and Long-Context Personalization
6. Real-Time Search and Retrieval-Grounded Answers
7. Collaborative Workspace and Artifacts
8. Enterprise and Team Governance
9. Safety, Oversight, and Policy Enforcement
10. Cost, Latency, and Routing Intelligence
11. Evaluation, Benchmarking, and Quality Operations
12. Platform and API Ecosystem Expansion

## L1 Seed Catalog (Grouped by L0)

### L0-01 Autonomous Task Execution and Browser/Computer Use

- L1-01-01 Browser action mode with takeover checkpoints
- L1-01-02 Multi-step task planning and resumable execution
- L1-01-03 Concurrent task sessions with per-task control
- L1-01-04 Sensitive action confirmation workflow

### L0-02 Agentic Coding and Dev Workflow Automation

- L1-02-01 Repo-aware coding agent with edit-run-verify loops
- L1-02-02 Bug-fix autopilot with rollback checkpoints
- L1-02-03 Code migration assistant for legacy stacks
- L1-02-04 Coding benchmark harness and regression gates

### L0-03 Native Multimodality (image, audio, video, docs)

- L1-03-01 Image understanding with chart/table extraction
- L1-03-02 Audio live interaction and voice agent surface
- L1-03-03 Video generation and editing orchestration
- L1-03-04 Document and mixed-media reasoning pipeline

### L0-04 Tool Calling and External Action Reliability

- L1-04-01 Robust tool call retries with typed error handling
- L1-04-02 Tool sandbox policy profiles by risk level
- L1-04-03 Tool result provenance and audit tracing
- L1-04-04 Human confirmation before irreversible actions

### L0-05 Memory and Long-Context Personalization

- L1-05-01 User preference memory with explicit controls
- L1-05-02 Session-to-session memory summaries
- L1-05-03 Long-context retrieval prioritization strategies
- L1-05-04 Memory privacy controls and retention policies

### L0-06 Real-Time Search and Retrieval-Grounded Answers

- L1-06-01 Built-in web retrieval with grounding citations
- L1-06-02 Search+tool workflows for multi-hop tasks
- L1-06-03 Hallucination guardrails for missing evidence
- L1-06-04 Retrieval quality scoring and feedback loop

### L0-07 Collaborative Workspace and Artifacts

- L1-07-01 Side-by-side artifact workspace for outputs
- L1-07-02 Iterative artifact editing with version history
- L1-07-03 Team-shared workspace contexts
- L1-07-04 Artifact export/import compatibility

### L0-08 Enterprise and Team Governance

- L1-08-01 Team policies for tool and data access
- L1-08-02 Role-based access control and approvals
- L1-08-03 Regional compliance and deployment controls
- L1-08-04 Enterprise connectors and managed integrations

### L0-09 Safety, Oversight, and Policy Enforcement

- L1-09-01 Multi-layer safety pipeline with monitor model
- L1-09-02 Prompt-injection and adversarial content defenses
- L1-09-03 Action policy gating for high-stakes tasks
- L1-09-04 Audit-ready safety event logging

### L0-10 Cost, Latency, and Routing Intelligence

- L1-10-01 Dynamic model routing by task complexity
- L1-10-02 Latency-aware fallback and cooldown behavior
- L1-10-03 Budget-aware inference and cost controls
- L1-10-04 SLO dashboards for p95/p99 and reliability

### L0-11 Evaluation, Benchmarking, and Quality Operations

- L1-11-01 Unified benchmark runner for agentic tasks
- L1-11-02 Continuous regression detection by capability cluster
- L1-11-03 Human feedback integration into quality tracking
- L1-11-04 Safety benchmark tracking and release gating

### L0-12 Platform and API Ecosystem Expansion

- L1-12-01 API parity for key assistant and agent features
- L1-12-02 Marketplace/connectors for third-party extensions
- L1-12-03 SDK and docs improvements for rapid adoption
- L1-12-04 Deployment profiles for self-hosted and enterprise

## High-Value Selection Rule Used

L1 item is promoted into L2 mapping when all conditions are true:

- Strong multi-competitor signal (appears in at least two ecosystems or one major launch).
- Strategic leverage for Nexus-AI differentiation and trust.
- Implementable in the current architecture with existing domain owners.
- Evidence can be attached through test/benchmark or route/module linkage.

## Output

High-value L1 items directly mapped to L2 IDs:

- `docs/registry/l1_to_l2_high_value_backlog_2026Q2.csv`
