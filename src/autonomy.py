import re
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Task and result datatypes
# ---------------------------------------------------------------------------

@dataclass
class Task:
    task_id: str
    name: str
    description: str
    priority: int = 3
    dependencies: List[str] = field(default_factory=list)
    estimated_hours: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SubtaskResult:
    task_id: str
    task_description: str
    agent_used: str
    result: str
    success: bool
    execution_time: float
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


_AGENT_PATTERNS: List[Tuple[str, List[str]]] = [
    ("coding", [
        r"\b(?:cod(?:e|ing)|implement|debug|test|function|class|refactor"
        r"|compil|syntax|bug|script|program|api|endpoint|module)\b",
    ]),
    ("research", [
        r"\b(?:research|search|find|look\s*up|summariz|source|cit|article"
        r"|paper|document|learn\s+about|what\s+is|explain)\b",
    ]),
    ("reasoning", [
        r"\b(?:reason|analyz|compar|decid|evaluat|pros?\s+and\s+cons"
        r"|trade-?off|logic|why|deduc|infer|assess)\b",
    ]),
    ("image_gen", [
        r"\b(?:generat(?:e|ing)\s+(?:an?\s+)?image|draw|paint|illustrat"
        r"|creat(?:e|ing)\s+(?:an?\s+)?(?:image|picture|photo|artwork)"
        r"|image\s+generat|text[\s-]to[\s-]image|stable\s*diffusion"
        r"|dall[\s-]?e|midjourney|render\s+(?:an?\s+)?image)\b",
    ]),
    ("video_gen", [
        r"\b(?:generat(?:e|ing)\s+(?:an?\s+)?video|creat(?:e|ing)\s+(?:an?\s+)?video"
        r"|animat(?:e|ion)|text[\s-]to[\s-]video|video\s+generat"
        r"|stable\s*video|motion\s+generat)\b",
    ]),
]

_COMPILED_PATTERNS = [
    (name, [re.compile(p, re.IGNORECASE) for p in patterns])
    for name, patterns in _AGENT_PATTERNS
]


def classify_subtask(task_description: str) -> str:
    scores: Dict[str, int] = {}
    lower = task_description.lower()
    for name, patterns in _COMPILED_PATTERNS:
        score = sum(len(p.findall(lower)) for p in patterns)
        if score > 0:
            scores[name] = score
    if not scores:
        return "reasoning"
    return max(scores, key=scores.get)


class PlanningSystem:
    def __init__(self, llm: Callable[[str, str], str], default_priority: int = 3):
        self.llm = llm
        self.default_priority = default_priority

    def decompose(self, goal: str, max_subtasks: int = 6) -> List[Task]:
        prompt = (
            "You are a project planning assistant. Break down the following goal into "
            "concrete, independently executable subtasks. Return a numbered list. "
            "If the goal is easy to execute directly, return exactly 'DIRECT'.\n\n"
            f"Goal: {goal}\n\n"
            f"Return at most {max_subtasks} subtasks in the form:\n"
            "1. <short subtask description>\n"
            "2. <short subtask description>\n"
        )
        try:
            raw = self.llm(prompt, goal)
        except Exception as exc:
            logger.warning("Planning LLM failed: %s", exc)
            return self._heuristic_decompose(goal)

        if raw.strip().upper().startswith("DIRECT"):
            return []

        tasks = self._parse_subtasks(raw, max_subtasks)
        return tasks or self._heuristic_decompose(goal)

    def _parse_subtasks(self, raw: str, limit: int) -> List[Task]:
        tasks: List[Task] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            m = re.match(r"^(?:\d+[.)]\s*|[-*]\s*)(.*)", line)
            if not m:
                continue
            description = m.group(1).strip()
            if not description:
                continue
            tasks.append(Task(
                task_id=str(len(tasks) + 1),
                name=description[:80],
                description=description,
                priority=self.default_priority,
            ))
            if len(tasks) >= limit:
                break
        return tasks

    def _heuristic_decompose(self, goal: str) -> List[Task]:
        lower = goal.lower()
        if any(x in lower for x in ["build", "create", "implement", "develop"]):
            return [
                Task("1", "Design architecture", f"Design an architecture for: {goal}", priority=4),
                Task("2", "Implement core functionality", "Implement the core functionality.", priority=5, dependencies=["1"]),
                Task("3", "Test and validate", "Test the implementation.", priority=4, dependencies=["2"]),
            ]
        if any(x in lower for x in ["deploy", "release", "publish"]):
            return [
                Task("1", "Prepare deployment", "Prepare the deployment environment.", priority=4),
                Task("2", "Deploy changes", "Deploy the code or service.", priority=5, dependencies=["1"]),
                Task("3", "Verify deployment", "Verify the deployment was successful.", priority=4, dependencies=["2"]),
            ]
        return [
            Task("1", "Analyze the goal", f"Analyze what is required for: {goal}", priority=3),
            Task("2", "Execute the work", f"Perform the required work for: {goal}", priority=4, dependencies=["1"]),
            Task("3", "Review results", "Review the results and summarize.", priority=3, dependencies=["2"]),
        ]


class Orchestrator:
    def __init__(self, llm: Callable[[str, str], str], max_parallel: int = 2):
        self.llm = llm
        self.planner = PlanningSystem(llm)
        self.max_parallel = max_parallel

    def execute(self, goal: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        ctx = context or {}
        max_subtasks = int(ctx.get("max_subtasks", 6))
        strategy = ctx.get("strategy", "parallel")

        start = time.monotonic()
        subtasks = self.planner.decompose(goal, max_subtasks)

        if not subtasks:
            single = self._execute_direct(goal)
            return {
                "result": single.result,
                "subtasks": [self._result_to_dict(single)],
                "execution_time": time.monotonic() - start,
                "plan_summary": f"Direct execution via {single.agent_used}",
            }

        assignments = self._assign_agents(subtasks)
        if strategy == "sequential" or len(assignments) == 1:
            results = self._execute_sequential(assignments)
        else:
            results = self._execute_parallel(assignments)

        return {
            "result": self._synthesize(goal, results),
            "subtasks": [self._result_to_dict(r) for r in results],
            "execution_time": time.monotonic() - start,
            "plan_summary": self._format_plan(assignments, results),
        }

    def _execute_direct(self, goal: str) -> SubtaskResult:
        agent_name = classify_subtask(goal)
        return self._execute_subtask({"id": "1", "description": goal}, agent_name, "")

    def _assign_agents(self, subtasks: List[Task]) -> List[Tuple[Task, str]]:
        result: List[Tuple[Task, str]] = []
        for task in subtasks:
            agent_name = classify_subtask(task.description)
            result.append((task, agent_name))
        return result

    def _execute_sequential(self, assignments: List[Tuple[Task, str]]) -> List[SubtaskResult]:
        results: List[SubtaskResult] = []
        context_text = ""
        for task, agent_name in assignments:
            result = self._execute_subtask(task, agent_name, context_text)
            if result.success:
                context_text += f"\n[Completed] {task.description}: {result.result[:200]}\n"
            results.append(result)
        return results

    def _execute_parallel(self, assignments: List[Tuple[Task, str]]) -> List[SubtaskResult]:
        results: List[Optional[SubtaskResult]] = [None] * len(assignments)
        with ThreadPoolExecutor(max_workers=self.max_parallel) as pool:
            futures = {}
            for idx, (task, agent_name) in enumerate(assignments):
                futures[pool.submit(self._execute_subtask, task, agent_name, "")] = idx
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    results[idx] = future.result(timeout=120)
                except Exception as exc:
                    task, agent_name = assignments[idx]
                    results[idx] = SubtaskResult(
                        task_id=task.task_id,
                        task_description=task.description,
                        agent_used=agent_name,
                        result="",
                        success=False,
                        execution_time=0.0,
                        error=str(exc),
                    )
        return [r for r in results if r is not None]

    def _execute_subtask(self, task: Task, agent_name: str, prior_context: str) -> SubtaskResult:
        prompt = self._build_agent_prompt(agent_name, task.description, prior_context)
        start = time.monotonic()
        try:
            response = self.llm(prompt, task.description)
            return SubtaskResult(
                task_id=task.task_id,
                task_description=task.description,
                agent_used=agent_name,
                result=response,
                success=True,
                execution_time=time.monotonic() - start,
            )
        except Exception as exc:
            return SubtaskResult(
                task_id=task.task_id,
                task_description=task.description,
                agent_used=agent_name,
                result="",
                success=False,
                execution_time=time.monotonic() - start,
                error=str(exc),
            )

    def _build_agent_prompt(self, agent_name: str, task: str, prior_context: str) -> str:
        role_prompts = {
            "coding": "You are a coding specialist. Write code, fix bugs, and explain implementation clearly.",
            "research": "You are a research specialist. Gather facts, summarize findings, and cite sources.",
            "reasoning": "You are a reasoning specialist. Analyze, compare options, and make a recommendation.",
            "image_gen": "You are an image prompt specialist.",
            "video_gen": "You are a video generation specialist.",
        }
        role = role_prompts.get(agent_name, "You are a general AI specialist.")
        context = f"\nContext:\n{prior_context}\n" if prior_context else ""
        return (
            f"{role}\n\n"
            f"Task: {task}\n"
            f"{context}"
            "Provide a concise, useful response."
        )

    def _synthesize(self, goal: str, results: List[SubtaskResult]) -> str:
        successes = [r for r in results if r.success]
        failures = [r for r in results if not r.success]
        if not successes:
            return "All subtasks failed: " + "; ".join(f"[{r.task_id}] {r.error}" for r in failures)
        if len(successes) == 1 and not failures:
            return successes[0].result
        summary = "".join(
            f"--- Subtask {r.task_id} ({r.agent_used}) ---\n{r.result}\n" for r in successes
        )
        if failures:
            summary += "\n--- Failed subtasks ---\n"
            summary += "\n".join(f"- {r.task_description}: {r.error}" for r in failures)
        try:
            prompt = (
                "You are synthesizing multiple subtask results into one coherent answer.\n\n"
                f"Original goal: {goal}\n\n"
                f"Subtask outputs:\n{summary}\n\n"
                "Provide a clear unified response that addresses the original goal."
            )
            return self.llm(prompt, goal)
        except Exception:
            return summary

    @staticmethod
    def _result_to_dict(result: SubtaskResult) -> Dict[str, Any]:
        return {
            "id": result.task_id,
            "description": result.task_description,
            "agent": result.agent_used,
            "result": result.result,
            "success": result.success,
            "error": result.error,
            "execution_time": result.execution_time,
        }

    @staticmethod
    def _format_plan(assignments: List[Tuple[Task, str]], results: List[SubtaskResult]) -> str:
        lines = []
        for (task, agent_name), result in zip(assignments, results):
            status = "✓" if result.success else "✗"
            lines.append(f"{status} [{task.task_id}] {task.description} → {agent_name} ({result.execution_time:.1f}s)")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# HierarchicalOrchestrator — Planner → Executor → Reviewer → Verifier
# ---------------------------------------------------------------------------

@dataclass
class ReviewResult:
    """Output of the Reviewer stage."""
    approved: bool
    feedback: str
    revised_output: str   # may be same as original if no revision needed
    confidence: float = 1.0


@dataclass
class VerificationResult:
    """Output of the Verifier stage."""
    goal_met: bool
    score: float          # 0.0 – 1.0
    summary: str
    gaps: List[str] = field(default_factory=list)


@dataclass
class HierarchicalResult:
    """Full output of a hierarchical orchestration run."""
    goal: str
    plan: List[Dict[str, Any]]
    execution: List[Dict[str, Any]]
    review: Dict[str, Any]
    verification: Dict[str, Any]
    final_output: str
    execution_time: float
    stages_completed: int           # 1 = plan only, 2 = +execute, 3 = +review, 4 = +verify


class HierarchicalOrchestrator:
    """Four-stage orchestrator: Planner → Executor → Reviewer → Verifier.

    Each stage is optional — the orchestrator degrades gracefully if the LLM
    fails, always returning the best available output rather than crashing.
    """

    _REVIEW_PROMPT = (
        "You are a senior engineer reviewing an AI-generated output.\n\n"
        "Original goal: {goal}\n\n"
        "Output to review:\n{output}\n\n"
        "Provide a structured review:\n"
        "1. APPROVED: yes/no\n"
        "2. ISSUES: list any problems (correctness, completeness, safety, clarity)\n"
        "3. REVISED OUTPUT: if issues found, provide the corrected version; "
        "otherwise repeat the original.\n"
        "4. CONFIDENCE: 0.0-1.0\n"
    )

    _VERIFY_PROMPT = (
        "You are a goal-verification agent.\n\n"
        "Original goal: {goal}\n\n"
        "Final output:\n{output}\n\n"
        "Answer ONLY in this JSON format:\n"
        '{{"goal_met": true/false, "score": 0.0-1.0, '
        '"summary": "one sentence", "gaps": ["gap1", "gap2"]}}\n'
    )

    def __init__(
        self,
        llm: Callable[[str, str], str],
        max_parallel: int = 2,
        skip_review: bool = False,
        skip_verify: bool = False,
    ):
        self.llm = llm
        self.planner = PlanningSystem(llm)
        self.executor = Orchestrator(llm, max_parallel=max_parallel)
        self.skip_review = skip_review
        self.skip_verify = skip_verify

    # ── public entry point ────────────────────────────────────────────────────

    def run(
        self,
        goal: str,
        context: Optional[Dict[str, Any]] = None,
        max_subtasks: int = 6,
    ) -> HierarchicalResult:
        ctx = context or {}
        max_subtasks = int(ctx.get("max_subtasks", max_subtasks))
        start = time.monotonic()

        # ── Stage 1: Plan ─────────────────────────────────────────────────────
        subtasks = self.planner.decompose(goal, max_subtasks)
        plan_dicts = [
            {"id": t.task_id, "description": t.description, "priority": t.priority}
            for t in subtasks
        ]
        stages_done = 1

        # ── Stage 2: Execute ──────────────────────────────────────────────────
        exec_result = self.executor.execute(goal, {"max_subtasks": max_subtasks})
        raw_output = exec_result.get("result", "")
        exec_subtasks = exec_result.get("subtasks", [])
        stages_done = 2

        # ── Stage 3: Review ───────────────────────────────────────────────────
        review_dict: Dict[str, Any] = {
            "approved": True, "feedback": "review skipped", "confidence": 1.0
        }
        reviewed_output = raw_output
        if not self.skip_review:
            try:
                rv = self._review(goal, raw_output)
                review_dict = {
                    "approved":   rv.approved,
                    "feedback":   rv.feedback,
                    "confidence": rv.confidence,
                }
                reviewed_output = rv.revised_output or raw_output
                stages_done = 3
            except Exception as exc:
                review_dict["feedback"] = f"review failed: {exc}"
                stages_done = 3  # still count it for transparency

        # ── Stage 4: Verify ───────────────────────────────────────────────────
        verify_dict: Dict[str, Any] = {
            "goal_met": True, "score": 1.0, "summary": "verification skipped", "gaps": []
        }
        if not self.skip_verify:
            try:
                vr = self._verify(goal, reviewed_output)
                verify_dict = {
                    "goal_met": vr.goal_met,
                    "score":    vr.score,
                    "summary":  vr.summary,
                    "gaps":     vr.gaps,
                }
                stages_done = 4
            except Exception as exc:
                verify_dict["summary"] = f"verification failed: {exc}"
                stages_done = 4

        return HierarchicalResult(
            goal=goal,
            plan=plan_dicts,
            execution=exec_subtasks,
            review=review_dict,
            verification=verify_dict,
            final_output=reviewed_output,
            execution_time=time.monotonic() - start,
            stages_completed=stages_done,
        )

    # ── Review stage ──────────────────────────────────────────────────────────

    def _review(self, goal: str, output: str) -> ReviewResult:
        prompt = self._REVIEW_PROMPT.format(goal=goal, output=output[:3000])
        raw = self.llm(prompt, goal)

        # Parse: look for APPROVED, ISSUES, REVISED OUTPUT, CONFIDENCE
        approved      = "yes" in raw.lower().split("approved")[-1][:30].lower() if "approved" in raw.lower() else True
        confidence    = 1.0
        feedback_parts: List[str] = []
        revised       = output   # default — unchanged

        for line in raw.splitlines():
            ll = line.lower().strip()
            if ll.startswith("2.") or ll.startswith("issues:"):
                feedback_parts.append(line.strip())
            if ll.startswith("4.") or ll.startswith("confidence:"):
                try:
                    num_str = re.search(r"(\d+(?:\.\d+)?)", line)
                    if num_str:
                        confidence = min(1.0, float(num_str.group(1)))
                except Exception:
                    pass

        # Extract revised output section
        m = re.search(
            r"(?:3\.\s*REVISED OUTPUT|REVISED OUTPUT)\s*[:\-]?\s*(.*?)(?=4\.|CONFIDENCE|$)",
            raw, re.DOTALL | re.IGNORECASE,
        )
        if m:
            candidate = m.group(1).strip()
            if candidate and len(candidate) > 20:
                revised = candidate

        return ReviewResult(
            approved=approved,
            feedback="\n".join(feedback_parts) if feedback_parts else "No issues found.",
            revised_output=revised,
            confidence=confidence,
        )

    # ── Verify stage ──────────────────────────────────────────────────────────

    def _verify(self, goal: str, output: str) -> VerificationResult:
        prompt = self._VERIFY_PROMPT.format(goal=goal, output=output[:3000])
        raw = self.llm(prompt, goal)

        # Try JSON parse
        try:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                import json as _json
                data = _json.loads(m.group(0))
                return VerificationResult(
                    goal_met = bool(data.get("goal_met", True)),
                    score    = float(data.get("score", 1.0)),
                    summary  = str(data.get("summary", "")),
                    gaps     = list(data.get("gaps", [])),
                )
        except Exception:
            pass

        # Fallback heuristic
        goal_met = "yes" in raw.lower() or "met" in raw.lower()
        return VerificationResult(goal_met=goal_met, score=0.7 if goal_met else 0.3, summary=raw[:200])

