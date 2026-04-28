# VersaAI Porting Tracker for Nexus-AI

This tracker holds subsystem porting status from VersaAI into Nexus-AI.

## Already Ported

- RAG subsystem baseline
- Complexity-based model routing
- Core orchestration/planning foundation
- Structured tool event streaming
- Autonomy routes (`/autonomy/execute`, `/autonomy/plan`, `/autonomy/trace/{trace_id}`)

## High Priority (Next)

- Safety core types and verdict model
- Input/output safety filters and central guardrail pipeline
- Prompt injection and PII detection
- Context window manager
- Research/reasoning engine primitives
- Model ensemble consensus layer
- Model base + registry foundations
- OpenAI-compatible API schema + typed error classes
- Typed tool framework and registry

## Medium Priority

- Extended planning agent wrappers
- Episodic memory improvements
- RAG critic and query decomposition
- Code-editor bridge integration
- Persistent user profile layer
- Cost governance and adaptive provider rate control

## Deferred / Skip

- C++ performance layer (defer until scale justifies)
- 3D model generation module (skip for now)
- Companion-style social persona module (skip)
- Blender ecosystem plugin as a core runtime dependency (defer)

## Porting Rule

For each ported module, require:

- Contract parity (input/output behavior)
- Test coverage for success and failure paths
- Clear migration note in commit/PR description
