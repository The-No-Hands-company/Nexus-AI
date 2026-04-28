"""src/simulation.py — SimulationEngine for swarm/persona-based prediction.

Consumed by TestSprintG simulation tests.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_json_safe(text: str, fallback: Any) -> Any:
    """Parse JSON from *text*, stripping markdown fences if present. Returns *fallback* on error."""
    cleaned = text.strip()
    # Strip ```json ... ``` or ``` ... ``` fences
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except Exception:
        return fallback


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class PersonaAgent:
    id: str
    name: str
    viewpoint: str
    role: str = "Participant"
    memory: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "viewpoint": self.viewpoint,
            "role": self.role,
            "memory": self.memory,
        }


@dataclass
class SimulationRound:
    round_number: int
    statements: list[dict[str, Any]] = field(default_factory=list)
    synthesis: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_number": self.round_number,
            "statements": self.statements,
            "synthesis": self.synthesis,
        }


@dataclass
class SimulationResult:
    sim_id: str
    topic: str
    n_personas: int
    n_rounds: int
    personas: list[PersonaAgent]
    rounds: list[SimulationRound]
    prediction: str
    confidence: float
    minority_views: list[str]
    report: str
    elapsed_sec: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "sim_id": self.sim_id,
            "topic": self.topic,
            "n_personas": self.n_personas,
            "n_rounds": self.n_rounds,
            "personas": [p.to_dict() for p in self.personas],
            "rounds": [r.to_dict() for r in self.rounds],
            "prediction": self.prediction,
            "confidence": self.confidence,
            "minority_views": self.minority_views,
            "report": self.report,
            "elapsed_sec": self.elapsed_sec,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class SimulationEngine:
    """Run a multi-persona deliberation simulation."""

    def __init__(
        self,
        llm: Callable,
        max_personas: int = 5,
        max_rounds: int = 3,
    ) -> None:
        self._llm = llm
        self.max_personas = max_personas
        self.max_rounds = max_rounds

    # ------------------------------------------------------------------
    # Internal prompt builders
    # ------------------------------------------------------------------

    def _generate_personas(self, topic: str, seed: str, n: int) -> list[PersonaAgent]:
        prompt = (
            f"Generate exactly {n} diverse expert personas as a JSON array. "
            f"Each element must have keys: id, name, role, viewpoint. "
            f"Topic: {topic}. Seed context: {seed}."
        )
        raw = self._llm([{"role": "user", "content": prompt}])
        data = _parse_json_safe(raw, [])
        if not isinstance(data, list):
            data = []
        personas: list[PersonaAgent] = []
        for i, item in enumerate(data[:n]):
            if not isinstance(item, dict):
                continue
            personas.append(PersonaAgent(
                id=item.get("id", f"p{i+1}"),
                name=item.get("name", f"Agent {i+1}"),
                viewpoint=item.get("viewpoint", ""),
                role=item.get("role", "Participant"),
            ))
        # Pad with defaults if LLM returned fewer
        while len(personas) < n:
            idx = len(personas) + 1
            personas.append(PersonaAgent(id=f"p{idx}", name=f"Agent {idx}", viewpoint="neutral"))
        return personas

    def _run_round(self, round_num: int, personas: list[PersonaAgent], topic: str) -> SimulationRound:
        statements: list[dict[str, Any]] = []
        for p in personas:
            prompt = (
                f"You are {p.name} ({p.role}). Your viewpoint: {p.viewpoint}. "
                f"Give a short statement on: {topic}"
            )
            raw = self._llm([{"role": "user", "content": prompt}])
            stmt = raw if isinstance(raw, str) else str(raw)
            p.memory.append(stmt)
            statements.append({"persona_id": p.id, "statement": stmt})

        synthesis_prompt = (
            f"Round {round_num} synthesis for topic: {topic}. "
            f"Summarise the key points from these statements: "
            + json.dumps(statements)
        )
        synthesis_raw = self._llm([{"role": "user", "content": synthesis_prompt}])
        synthesis = synthesis_raw if isinstance(synthesis_raw, str) else ""
        return SimulationRound(round_number=round_num, statements=statements, synthesis=synthesis)

    def _final_synthesis(self, topic: str, rounds: list[SimulationRound]) -> dict[str, Any]:
        history = json.dumps([r.to_dict() for r in rounds])
        prompt = (
            f"Based on the deliberation rounds, provide a synthesis and predict the outcome. "
            f"Topic: {topic}. Rounds: {history}. "
            f"Return a JSON object with keys: prediction, confidence (0-1 float), "
            f"key_drivers (list), minority_views (list), report (markdown string)."
        )
        raw = self._llm([{"role": "user", "content": prompt}])
        return _parse_json_safe(raw, {
            "prediction": "Unknown",
            "confidence": 0.5,
            "key_drivers": [],
            "minority_views": [],
            "report": "",
        })

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        topic: str,
        seed: str = "",
        n_personas: int = 3,
        n_rounds: int = 2,
    ) -> SimulationResult:
        t0 = time.perf_counter()
        n_personas = min(n_personas, self.max_personas)
        n_rounds = min(n_rounds, self.max_rounds)

        personas = self._generate_personas(topic, seed, n_personas)
        rounds: list[SimulationRound] = []
        for r in range(1, n_rounds + 1):
            rounds.append(self._run_round(r, personas, topic))

        synthesis = self._final_synthesis(topic, rounds)

        return SimulationResult(
            sim_id=str(uuid.uuid4()),
            topic=topic,
            n_personas=len(personas),
            n_rounds=len(rounds),
            personas=personas,
            rounds=rounds,
            prediction=synthesis.get("prediction", ""),
            confidence=float(synthesis.get("confidence", 0.5)),
            minority_views=synthesis.get("minority_views", []),
            report=synthesis.get("report", ""),
            elapsed_sec=time.perf_counter() - t0,
        )


def export_training_dataset(sim_dicts: list[dict]) -> list[dict]:
    """Convert simulation result dicts into prompt/response training pairs."""
    rows: list[dict] = []
    for sim in sim_dicts:
        topic = str(sim.get("topic") or "")
        report = str(sim.get("report") or sim.get("prediction") or "")
        if topic and report:
            rows.append({"prompt": topic, "response": report})
        for rnd in sim.get("rounds", []):
            for statement in rnd.get("statements", []):
                persona = str(statement.get("persona") or "")
                content = str(statement.get("statement") or statement.get("content") or "")
                if persona and content:
                    rows.append({"prompt": f"[{persona}] {topic}", "response": content})
    return rows
