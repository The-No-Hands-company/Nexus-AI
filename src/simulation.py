"""Nexus AI Simulation Engine — Sprint G (Phase 2: Multi-Agent Empire).

Inspired by MiroFish swarm-intelligence approach (github.com/666ghj/MiroFish).
No MiroFish code is used; this is an original implementation.

Architecture:
- Seed material is chunked and summarised to extract key entities and positions.
- N persona-agents are generated, each with a distinct viewpoint derived from the seed.
- Agents interact in configurable rounds; each round produces a set of position updates.
- A synthesis pass produces a structured prediction report.
"""
from __future__ import annotations
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class PersonaAgent:
    id: str
    name: str
    viewpoint: str          # One-sentence position summary
    role: str               # e.g. "optimist", "skeptic", "expert", "contrarian"
    memory: List[str] = field(default_factory=list)  # accumulated round summaries

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id":        self.id,
            "name":      self.name,
            "viewpoint": self.viewpoint,
            "role":      self.role,
            "memory":    self.memory,
        }


@dataclass
class RoundSummary:
    round_num: int
    interactions: List[Dict[str, str]]  # [{"persona": name, "statement": text}]
    consensus_shift: str                # brief description of how consensus moved
    key_points: List[str]


@dataclass
class SimulationResult:
    sim_id: str
    topic: str
    n_personas: int
    n_rounds: int
    personas: List[PersonaAgent]
    rounds: List[RoundSummary]
    prediction: str
    confidence: float
    minority_views: List[str]
    report: str
    elapsed_sec: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sim_id":        self.sim_id,
            "topic":         self.topic,
            "n_personas":    self.n_personas,
            "n_rounds":      self.n_rounds,
            "personas":      [p.to_dict() for p in self.personas],
            "rounds":        [
                {
                    "round_num":        r.round_num,
                    "interactions":     r.interactions,
                    "consensus_shift":  r.consensus_shift,
                    "key_points":       r.key_points,
                }
                for r in self.rounds
            ],
            "prediction":    self.prediction,
            "confidence":    self.confidence,
            "minority_views": self.minority_views,
            "report":        self.report,
            "elapsed_sec":   round(self.elapsed_sec, 2),
        }


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_persona_gen_prompt(topic: str, seed: str, n: int) -> str:
    seed_section = f"\n\nSeed material:\n{seed[:2000]}" if seed.strip() else ""
    return (
        f"You are generating {n} distinct persona-agents for a swarm simulation about: "
        f'"{topic}".{seed_section}\n\n'
        f"Create exactly {n} personas with diverse viewpoints (optimist, skeptic, expert, "
        f"contrarian, pragmatist, idealist, etc.). Each persona must have a unique perspective.\n\n"
        f"Reply with ONLY a JSON array (no fences, no extra text):\n"
        f'[\n'
        f'  {{"id":"p1","name":"Dr. Chen Wei","viewpoint":"one-sentence-position","role":"expert"}},\n'
        f'  ...\n'
        f']'
    )


def _build_round_prompt(topic: str, persona: PersonaAgent, round_num: int,
                        other_statements: List[str], seed: str) -> str:
    context = "\n".join(other_statements[-4:]) if other_statements else "No prior statements yet."
    memory  = "\n".join(persona.memory[-3:]) if persona.memory else "None"
    seed_ctx = f"\nSeed context: {seed[:800]}" if seed.strip() and round_num == 1 else ""
    return (
        f'Simulation: "{topic}"\n'
        f"You are {persona.name} ({persona.role}). Your position: {persona.viewpoint}{seed_ctx}\n\n"
        f"Your memory:\n{memory}\n\n"
        f"Recent statements from others:\n{context}\n\n"
        f"Round {round_num}: Give a single concise statement (1–3 sentences) advancing your position, "
        f"engaging with what others said. Be specific and opinionated.\n\n"
        f'Reply with ONLY a JSON object: {{"statement": "your statement here"}}'
    )


def _build_synthesis_prompt(topic: str, rounds: List[RoundSummary],
                             personas: List[PersonaAgent], seed: str) -> str:
    all_statements = []
    for r in rounds:
        for interaction in r.interactions:
            all_statements.append(f"[{interaction['persona']}] {interaction['statement']}")
    digest = "\n".join(all_statements[-20:])  # last 20 statements

    seed_section = f"\nOriginal seed:\n{seed[:1000]}\n" if seed.strip() else ""
    return (
        f'Simulation complete. Topic: "{topic}"{seed_section}\n\n'
        f"Simulation digest (last statements):\n{digest}\n\n"
        f"Persona viewpoints:\n" +
        "\n".join(f"- {p.name} ({p.role}): {p.viewpoint}" for p in personas) +
        "\n\nWrite a structured prediction report. Reply with ONLY JSON (no fences):\n"
        "{\n"
        '  "prediction": "one clear prediction sentence",\n'
        '  "confidence": 0.72,\n'
        '  "key_drivers": ["driver1", "driver2", "driver3"],\n'
        '  "minority_views": ["view1", "view2"],\n'
        '  "report": "3-5 paragraph detailed report in markdown"\n'
        "}"
    )


def _build_round_summary_prompt(topic: str, round_num: int,
                                 interactions: List[Dict[str, str]]) -> str:
    statements = "\n".join(
        f"- {i['persona']}: {i['statement']}" for i in interactions
    )
    return (
        f'Summarise Round {round_num} of the simulation about "{topic}".\n'
        f"Statements:\n{statements}\n\n"
        "Reply with ONLY JSON:\n"
        '{"consensus_shift": "one sentence", "key_points": ["point1", "point2", "point3"]}'
    )


# ---------------------------------------------------------------------------
# Safe LLM response parsers
# ---------------------------------------------------------------------------

def _parse_json_safe(text: str, fallback: Any) -> Any:
    """Strip any accidental markdown fences and parse JSON."""
    cleaned = text.strip()
    # Strip ```json ... ``` or ``` ... ```
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        # parts[0]='' (before first fence), parts[1]=content block, rest=trailing
        if len(parts) >= 2:
            cleaned = parts[1].strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
    try:
        return json.loads(cleaned)
    except Exception:
        return fallback


# ---------------------------------------------------------------------------
# Simulation engine
# ---------------------------------------------------------------------------

LLMFn = Callable[[List[Dict[str, str]]], str]


class SimulationEngine:
    """Lightweight swarm prediction engine.

    `llm_fn` must accept a list of OpenAI-style message dicts and return a
    plain string (the raw LLM text).  The agent layer passes a thin wrapper
    around `call_llm_with_fallback`.
    """

    def __init__(self, llm_fn: LLMFn, max_personas: int = 8, max_rounds: int = 5) -> None:
        self._llm = llm_fn
        self._max_personas = max_personas
        self._max_rounds   = max_rounds

    def _call(self, prompt: str) -> str:
        try:
            return self._llm([{"role": "user", "content": prompt}])
        except Exception as e:
            return f'{{"error": "{e}"}}'

    # ------------------------------------------------------------------

    def _generate_personas(self, topic: str, seed: str, n: int) -> List[PersonaAgent]:
        prompt = _build_persona_gen_prompt(topic, seed, n)
        resp   = self._call(prompt)
        raw    = _parse_json_safe(resp, [])
        agents: List[PersonaAgent] = []
        if isinstance(raw, list):
            for i, item in enumerate(raw[:n]):
                if isinstance(item, dict):
                    agents.append(PersonaAgent(
                        id        = item.get("id", f"p{i+1}"),
                        name      = item.get("name", f"Agent {i+1}"),
                        viewpoint = item.get("viewpoint", "Neutral perspective"),
                        role      = item.get("role", "observer"),
                    ))
        # Pad with defaults if LLM returned fewer than requested
        fallback_roles = ["optimist","skeptic","expert","contrarian","pragmatist",
                          "idealist","analyst","critic"]
        while len(agents) < n:
            idx = len(agents)
            agents.append(PersonaAgent(
                id        = f"p{idx+1}",
                name      = f"Persona {idx+1}",
                viewpoint = "Considers multiple perspectives",
                role      = fallback_roles[idx % len(fallback_roles)],
            ))
        return agents

    def _run_round(self, topic: str, round_num: int,
                   personas: List[PersonaAgent], seed: str) -> RoundSummary:
        interactions: List[Dict[str, str]] = []
        all_statements: List[str] = []

        for persona in personas:
            prompt = _build_round_prompt(
                topic, persona, round_num, all_statements, seed
            )
            resp   = self._call(prompt)
            parsed = _parse_json_safe(resp, {})
            statement = (
                parsed.get("statement", resp[:200])
                if isinstance(parsed, dict) else resp[:200]
            )
            interactions.append({"persona": persona.name, "statement": statement})
            all_statements.append(f"{persona.name}: {statement}")
            # Store in persona memory
            persona.memory.append(f"[Round {round_num}] {statement}")

        # Build round summary
        summary_prompt = _build_round_summary_prompt(topic, round_num, interactions)
        summary_resp   = self._call(summary_prompt)
        summary_data   = _parse_json_safe(summary_resp, {})
        consensus_shift = (
            summary_data.get("consensus_shift", "Debate continued")
            if isinstance(summary_data, dict) else "Debate continued"
        )
        key_points = (
            summary_data.get("key_points", [])
            if isinstance(summary_data, dict) else []
        )

        return RoundSummary(
            round_num      = round_num,
            interactions   = interactions,
            consensus_shift= consensus_shift,
            key_points     = key_points if isinstance(key_points, list) else [],
        )

    def _synthesise(self, topic: str, rounds: List[RoundSummary],
                    personas: List[PersonaAgent], seed: str) -> Dict[str, Any]:
        prompt = _build_synthesis_prompt(topic, rounds, personas, seed)
        resp   = self._call(prompt)
        data   = _parse_json_safe(resp, {})
        if not isinstance(data, dict):
            data = {}
        return {
            "prediction":    data.get("prediction", "Outcome unclear from simulation."),
            "confidence":    float(data.get("confidence", 0.5)),
            "key_drivers":   data.get("key_drivers", []),
            "minority_views":data.get("minority_views", []),
            "report":        data.get("report", resp[:2000]),
        }

    # ------------------------------------------------------------------

    def run(
        self,
        topic: str,
        seed: str = "",
        n_personas: int = 5,
        n_rounds: int = 3,
        scenario: Optional[str] = None,
    ) -> SimulationResult:
        """Run a complete swarm simulation and return a structured result.

        If `scenario` is given it is looked up in SCENARIO_LIBRARY and used
        to seed `topic` and `seed` unless those are explicitly provided.
        """
        if scenario and scenario in SCENARIO_LIBRARY:
            tmpl = SCENARIO_LIBRARY[scenario]
            if not topic or topic == tmpl.get("topic", ""):
                topic = topic or tmpl["topic"]
            seed  = seed or tmpl.get("seed", "")
            n_personas = n_personas if n_personas != 5 else tmpl.get("n_personas", n_personas)
            n_rounds   = n_rounds   if n_rounds   != 3 else tmpl.get("n_rounds",   n_rounds)
        n_personas = max(2, min(n_personas, self._max_personas))
        n_rounds   = max(1, min(n_rounds,   self._max_rounds))
        sim_id     = uuid.uuid4().hex[:12]
        t0         = time.time()

        personas = self._generate_personas(topic, seed, n_personas)
        rounds: List[RoundSummary] = []

        for r in range(1, n_rounds + 1):
            round_result = self._run_round(topic, r, personas, seed)
            rounds.append(round_result)

        synthesis = self._synthesise(topic, rounds, personas, seed)

        return SimulationResult(
            sim_id        = sim_id,
            topic         = topic,
            n_personas    = n_personas,
            n_rounds      = n_rounds,
            personas      = personas,
            rounds        = rounds,
            prediction    = synthesis["prediction"],
            confidence    = synthesis["confidence"],
            minority_views= synthesis.get("minority_views", []),
            report        = synthesis["report"],
            elapsed_sec   = time.time() - t0,
        )


# ---------------------------------------------------------------------------
# Scenario library — pre-built simulation templates
# ---------------------------------------------------------------------------

SCENARIO_LIBRARY: Dict[str, Dict[str, Any]] = {
    "ai_regulation": {
        "topic": "Should advanced AI development be regulated by governments?",
        "seed": (
            "Recent advances in large language models have prompted calls for "
            "mandatory safety evaluations, compute thresholds, and liability "
            "frameworks. Critics argue regulation stifles innovation and is "
            "technically infeasible. Proponents cite existential risk."
        ),
        "n_personas": 6,
        "n_rounds": 3,
    },
    "climate_policy": {
        "topic": "What is the most effective global climate policy for 2030?",
        "seed": (
            "IPCC reports indicate 1.5°C threshold may be crossed by 2035 "
            "without drastic action. Options include carbon tax, cap-and-trade, "
            "green new deals, and nuclear energy expansion."
        ),
        "n_personas": 5,
        "n_rounds": 4,
    },
    "ubi_economics": {
        "topic": "Would universal basic income improve societal well-being?",
        "seed": (
            "UBI pilots in Finland, Kenya, and Stockton CA show mixed results: "
            "improved mental health and small employment upticks vs. concerns "
            "about inflation, funding, and work disincentives."
        ),
        "n_personas": 5,
        "n_rounds": 3,
    },
    "remote_work": {
        "topic": "Is remote work better for productivity and talent retention than office work?",
        "seed": (
            "Post-pandemic data shows 30% of knowledge workers now fully remote. "
            "Studies are conflicted: some show 13% productivity gains, others show "
            "collaboration deficits and harder onboarding."
        ),
        "n_personas": 4,
        "n_rounds": 3,
    },
    "crypto_future": {
        "topic": "Will cryptocurrencies replace traditional financial systems by 2040?",
        "seed": (
            "Bitcoin and Ethereum have market caps exceeding $1T combined. "
            "CBDCs are being piloted by 130+ countries. DeFi protocols process "
            "billions daily but face regulatory pressure and volatility."
        ),
        "n_personas": 5,
        "n_rounds": 3,
    },
    "space_colonisation": {
        "topic": "Should humanity prioritise Mars colonisation in the next 20 years?",
        "seed": (
            "SpaceX Starship aims to land humans on Mars by 2030. NASA Artemis "
            "focuses on the Moon first. Critics argue resources should go to "
            "solving Earth's problems first. Proponents cite species survival."
        ),
        "n_personas": 5,
        "n_rounds": 3,
    },
}


# ---------------------------------------------------------------------------
# Simulation comparison (A/B diffing)
# ---------------------------------------------------------------------------

def compare_simulations(
    sim_a: Dict[str, Any],
    sim_b: Dict[str, Any],
) -> Dict[str, Any]:
    """Diff two SimulationResult dicts and return a structured comparison.

    Parameters
    ----------
    sim_a, sim_b : dicts produced by ``SimulationResult.to_dict()``

    Returns
    -------
    dict with keys:
        same_topic, confidence_delta, prediction_agreement,
        a_only_drivers, b_only_drivers, shared_drivers,
        a_only_minority, b_only_minority,
        round_count_delta, persona_count_delta, summary
    """
    same_topic = sim_a.get("topic") == sim_b.get("topic")

    conf_a = float(sim_a.get("confidence", 0.5))
    conf_b = float(sim_b.get("confidence", 0.5))
    confidence_delta = round(conf_b - conf_a, 4)

    pred_a = str(sim_a.get("prediction", "")).strip().lower()
    pred_b = str(sim_b.get("prediction", "")).strip().lower()
    prediction_agreement = pred_a == pred_b

    # key_drivers comparison — available in synthesis data
    drivers_a = set(sim_a.get("key_drivers", []))
    drivers_b = set(sim_b.get("key_drivers", []))
    shared_drivers  = sorted(drivers_a & drivers_b)
    a_only_drivers  = sorted(drivers_a - drivers_b)
    b_only_drivers  = sorted(drivers_b - drivers_a)

    minority_a = set(sim_a.get("minority_views", []))
    minority_b = set(sim_b.get("minority_views", []))
    a_only_minority = sorted(minority_a - minority_b)
    b_only_minority = sorted(minority_b - minority_a)

    round_delta   = int(sim_b.get("n_rounds", 0))   - int(sim_a.get("n_rounds", 0))
    persona_delta = int(sim_b.get("n_personas", 0)) - int(sim_a.get("n_personas", 0))

    summary_parts = []
    if same_topic:
        summary_parts.append("Both simulations share the same topic.")
    else:
        summary_parts.append(
            f"Topics differ: A='{sim_a.get('topic','')}' vs B='{sim_b.get('topic','')}'"
        )
    if prediction_agreement:
        summary_parts.append("Predictions agree.")
    else:
        summary_parts.append("Predictions diverge.")
    summary_parts.append(
        f"Confidence shift: {conf_a:.2f} → {conf_b:.2f} (Δ{confidence_delta:+.3f})."
    )
    if shared_drivers:
        summary_parts.append(f"Shared drivers: {', '.join(shared_drivers[:3])}.")

    return {
        "same_topic":            same_topic,
        "confidence_delta":      confidence_delta,
        "prediction_agreement":  prediction_agreement,
        "a_only_drivers":        a_only_drivers,
        "b_only_drivers":        b_only_drivers,
        "shared_drivers":        shared_drivers,
        "a_only_minority":       a_only_minority,
        "b_only_minority":       b_only_minority,
        "round_count_delta":     round_delta,
        "persona_count_delta":   persona_delta,
        "summary":               " ".join(summary_parts),
    }


# ---------------------------------------------------------------------------
# Training signal export (simulation → fine-tuning dataset)
# ---------------------------------------------------------------------------

def export_training_dataset(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert a list of SimulationResult dicts into an OpenAI fine-tuning JSONL format.

    Each simulation becomes one training example:
      - system: describes the simulation context
      - user:   the topic
      - assistant: the structured prediction report

    Returns a list of {"messages": [...]} dicts, one per simulation.
    """
    dataset: List[Dict[str, Any]] = []
    for result in results:
        topic      = result.get("topic", "")
        report     = result.get("report", "")
        prediction = result.get("prediction", "")
        confidence = result.get("confidence", 0.5)
        minority   = result.get("minority_views", [])

        system_msg = (
            "You are a multi-agent swarm simulation engine. "
            "Given a topic, produce a structured prediction report "
            "including a clear prediction, confidence score, key drivers, "
            "minority views, and a detailed analysis."
        )
        user_msg = f"Run a swarm simulation about: {topic}"
        assistant_msg = json.dumps({
            "prediction":    prediction,
            "confidence":    confidence,
            "minority_views": minority,
            "report":        report,
        }, ensure_ascii=False)

        dataset.append({
            "messages": [
                {"role": "system",    "content": system_msg},
                {"role": "user",      "content": user_msg},
                {"role": "assistant", "content": assistant_msg},
            ]
        })
    return dataset
