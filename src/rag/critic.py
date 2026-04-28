from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CritiqueResult:
    overall_score: float
    notes: str

    def to_dict(self) -> dict:
        return {"overall_score": self.overall_score, "notes": self.notes}


class CriticAgent:
    def critique(self, query: str, answer: str, results: list[dict]) -> CritiqueResult:
        if not results:
            return CritiqueResult(overall_score=0.0, notes="No retrieval context")
        answer_lower = (answer or "").lower()
        overlap = sum(1 for item in results if str(item.get("document", "")).lower().split(" ")[0] in answer_lower)
        score = min(1.0, 0.5 + (0.1 * overlap))
        return CritiqueResult(overall_score=score, notes="Critique generated from retrieval overlap")