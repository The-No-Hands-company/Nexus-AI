"""
Production-grade Critic Agent for RAG quality assessment.

The Critic Agent evaluates RAG outputs for:
- Factual accuracy
- Relevance to query
- Completeness
- Coherence and consistency
- Citation quality
- Hallucination detection
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import re
import logging

logger = logging.getLogger(__name__)
from .logging_compat import HAS_CPP_LOGGER


class CriticDimension(Enum):
    """Dimensions for critique evaluation."""
    FACTUALITY = "factuality"  # Are facts correct?
    RELEVANCE = "relevance"  # Does answer address query?
    COMPLETENESS = "completeness"  # Is answer complete?
    COHERENCE = "coherence"  # Is answer coherent?
    CITATION = "citation"  # Are sources cited properly?
    HALLUCINATION = "hallucination"  # Any hallucinated content?
    CONSISTENCY = "consistency"  # Is answer internally consistent?


class CriticSeverity(Enum):
    """Severity levels for critique issues."""
    CRITICAL = "critical"  # Must fix
    HIGH = "high"  # Should fix
    MEDIUM = "medium"  # Nice to fix
    LOW = "low"  # Optional improvement
    INFO = "info"  # Informational only


@dataclass
class CriticIssue:
    """An issue found during critique."""

    dimension: CriticDimension
    severity: CriticSeverity
    description: str
    location: Optional[str] = None  # Where in answer
    suggestion: Optional[str] = None  # How to fix
    evidence: Optional[str] = None  # Supporting evidence
    confidence: float = 1.0  # Confidence in this issue (0-1)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "dimension": self.dimension.value,
            "severity": self.severity.value,
            "description": self.description,
            "location": self.location,
            "suggestion": self.suggestion,
            "evidence": self.evidence,
            "confidence": self.confidence
        }


@dataclass
class DimensionScore:
    """Score for a single critique dimension."""

    dimension: CriticDimension
    score: float  # 0.0 (worst) to 1.0 (best)
    issues: List[CriticIssue] = field(default_factory=list)
    reasoning: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "dimension": self.dimension.value,
            "score": self.score,
            "issues": [issue.to_dict() for issue in self.issues],
            "reasoning": self.reasoning
        }


@dataclass
class Critique:
    """Complete critique of a RAG output."""

    query: str
    answer: str
    retrieved_docs: List[Dict[str, Any]]
    dimension_scores: List[DimensionScore]
    overall_score: float = 0.0
    issues: List[CriticIssue] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def __post_init__(self):
        """Calculate overall score and aggregate issues."""
        if self.dimension_scores:
            self.overall_score = sum(
                ds.score for ds in self.dimension_scores
            ) / len(self.dimension_scores)

            # Aggregate all issues
            self.issues = []
            for ds in self.dimension_scores:
                self.issues.extend(ds.issues)

            # Sort by severity
            severity_order = {
                CriticSeverity.CRITICAL: 0,
                CriticSeverity.HIGH: 1,
                CriticSeverity.MEDIUM: 2,
                CriticSeverity.LOW: 3,
                CriticSeverity.INFO: 4
            }
            self.issues.sort(key=lambda x: severity_order[x.severity])

    def get_critical_issues(self) -> List[CriticIssue]:
        """Get only critical issues."""
        return [
            issue for issue in self.issues
            if issue.severity == CriticSeverity.CRITICAL
        ]

    def is_acceptable(self, min_score: float = 0.7) -> bool:
        """Check if output quality is acceptable."""
        return (
            self.overall_score >= min_score and
            len(self.get_critical_issues()) == 0
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query": self.query,
            "overall_score": self.overall_score,
            "dimension_scores": [ds.to_dict() for ds in self.dimension_scores],
            "issues": [issue.to_dict() for issue in self.issues],
            "recommendations": self.recommendations,
            "metadata": self.metadata,
            "timestamp": self.timestamp
        }


@dataclass
class CriticConfig:
    """Configuration for Critic Agent."""

    use_llm: bool = False
    llm_model: Optional[Any] = None
    enabled_dimensions: List[CriticDimension] = field(
        default_factory=lambda: list(CriticDimension)
    )
    min_acceptable_score: float = 0.7
    check_citations: bool = True
    check_hallucinations: bool = True
    strict_mode: bool = False  # More rigorous evaluation


class CriticAgent:
    """
    Production-grade Critic Agent for RAG quality assessment.

    Evaluates:
    - Factual accuracy against retrieved documents
    - Relevance to original query
    - Completeness of answer
    - Coherence and flow
    - Citation quality
    - Hallucination detection
    - Internal consistency
    """

    def __init__(self, config: Optional[CriticConfig] = None):
        """
        Initialize Critic Agent.

        Args:
            config: Critic configuration
        """
        self.config = config or CriticConfig()

        # Initialize critique patterns
        self._init_patterns()

        # Statistics
        self.stats = {
            "total_critiques": 0,
            "average_score": 0.0,
            "critical_issues_found": 0
        }

        if HAS_CPP_LOGGER:
            logger.info(
                f"CriticAgent initialized (LLM: {self.config.use_llm}, "
                f"dimensions: {len(self.config.enabled_dimensions)})",
                "CriticAgent"
            )
        else:
            logger.info(
                f"CriticAgent initialized (LLM: {self.config.use_llm}, "
                f"dimensions: {len(self.config.enabled_dimensions)})"
            )

    def _init_patterns(self):
        """Initialize regex patterns for heuristic evaluation."""
        self.patterns = {
            "citation": re.compile(r"\[\d+\]|\(\d+\)|according to|as stated in", re.IGNORECASE),
            "uncertainty": re.compile(
                r"\b(maybe|perhaps|possibly|likely|probably|seems|appears)\b",
                re.IGNORECASE
            ),
            "definitive": re.compile(
                r"\b(definitely|certainly|clearly|obviously|always|never)\b",
                re.IGNORECASE
            ),
            "question": re.compile(r"\?$"),
            "incomplete": re.compile(r"\.\.\.$|etc\.$"),
        }

    def critique(
        self,
        query: str,
        answer: str,
        retrieved_docs: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None
    ) -> Critique:
        """
        Perform comprehensive critique of RAG output.

        Args:
            query: Original user query
            answer: Generated answer
            retrieved_docs: Documents used for generation
            metadata: Optional additional metadata

        Returns:
            Complete critique with scores and issues
        """
        if HAS_CPP_LOGGER:
            logger.info(f"Critiquing answer for query: {query[:100]}...", "CriticAgent")
        else:
            logger.info(f"Critiquing answer for query: {query[:100]}...")

        dimension_scores = []

        # Evaluate each enabled dimension
        for dimension in self.config.enabled_dimensions:
            if dimension == CriticDimension.FACTUALITY:
                score = self._evaluate_factuality(answer, retrieved_docs)
            elif dimension == CriticDimension.RELEVANCE:
                score = self._evaluate_relevance(query, answer)
            elif dimension == CriticDimension.COMPLETENESS:
                score = self._evaluate_completeness(query, answer)
            elif dimension == CriticDimension.COHERENCE:
                score = self._evaluate_coherence(answer)
            elif dimension == CriticDimension.CITATION:
                score = self._evaluate_citations(answer, retrieved_docs)
            elif dimension == CriticDimension.HALLUCINATION:
                score = self._evaluate_hallucination(answer, retrieved_docs)
            elif dimension == CriticDimension.CONSISTENCY:
                score = self._evaluate_consistency(answer)
            else:
                continue

            dimension_scores.append(score)

        # Generate recommendations
        recommendations = self._generate_recommendations(dimension_scores)

        # Create critique
        critique = Critique(
            query=query,
            answer=answer,
            retrieved_docs=retrieved_docs,
            dimension_scores=dimension_scores,
            recommendations=recommendations,
            metadata=metadata or {}
        )

        # Update statistics
        self.stats["total_critiques"] += 1
        self.stats["average_score"] = (
            (self.stats["average_score"] * (self.stats["total_critiques"] - 1) +
             critique.overall_score) / self.stats["total_critiques"]
        )
        self.stats["critical_issues_found"] += len(critique.get_critical_issues())

        if HAS_CPP_LOGGER:
            logger.info(
                f"Critique complete: score={critique.overall_score:.2f}, "
                f"issues={len(critique.issues)}",
                "CriticAgent"
            )
        else:
            logger.info(
                f"Critique complete: score={critique.overall_score:.2f}, "
                f"issues={len(critique.issues)}"
            )

        return critique

    def _evaluate_factuality(
        self,
        answer: str,
        retrieved_docs: List[Dict[str, Any]]
    ) -> DimensionScore:
        """Evaluate factual accuracy against retrieved documents."""
        issues = []

        # Extract facts from answer (simplified)
        answer_sentences = answer.split('.')

        # Check if facts are supported by retrieved documents
        doc_texts = [doc.get("document", "") for doc in retrieved_docs]
        all_doc_text = " ".join(doc_texts).lower()

        unsupported_count = 0
        for sentence in answer_sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            # Simple check: key phrases in sentence should appear in docs
            key_words = [w for w in sentence.lower().split() if len(w) > 4]
            if key_words:
                support_score = sum(1 for w in key_words if w in all_doc_text) / len(key_words)

                if support_score < 0.3:
                    unsupported_count += 1
                    issues.append(CriticIssue(
                        dimension=CriticDimension.FACTUALITY,
                        severity=CriticSeverity.HIGH,
                        description="Statement may not be supported by retrieved documents",
                        location=sentence[:100],
                        suggestion="Verify against source documents or add citation",
                        confidence=0.7
                    ))

        # Calculate score
        if len(answer_sentences) > 0:
            score = 1.0 - (unsupported_count / len(answer_sentences))
        else:
            score = 0.5

        return DimensionScore(
            dimension=CriticDimension.FACTUALITY,
            score=max(0.0, min(1.0, score)),
            issues=issues,
            reasoning=f"Found {unsupported_count} potentially unsupported statements"
        )

    def _evaluate_relevance(self, query: str, answer: str) -> DimensionScore:
        """Evaluate how well answer addresses the query."""
        issues = []

        # Extract key terms, stripping punctuation for accurate matching
        _strip = str.maketrans("", "", ".,;:!?\"'()[]{}—–-")
        query_terms = {w.translate(_strip) for w in query.lower().split()} - {""}
        answer_terms = {w.translate(_strip) for w in answer.lower().split()} - {""}

        # Calculate term overlap
        overlap = len(query_terms & answer_terms)
        relevance_score = overlap / len(query_terms) if query_terms else 0.0

        # Check if answer addresses query type (what, how, why, etc.)
        query_type = self._extract_query_type(query)
        if query_type and not self._answer_matches_query_type(answer, query_type):
            issues.append(CriticIssue(
                dimension=CriticDimension.RELEVANCE,
                severity=CriticSeverity.HIGH,
                description=f"Answer doesn't properly address '{query_type}' query",
                suggestion=f"Ensure answer provides {query_type} information",
                confidence=0.8
            ))
            relevance_score *= 0.7

        # Check for off-topic content
        if relevance_score < 0.3:
            issues.append(CriticIssue(
                dimension=CriticDimension.RELEVANCE,
                severity=CriticSeverity.CRITICAL,
                description="Answer appears off-topic or doesn't address query",
                suggestion="Regenerate answer focusing on query intent",
                confidence=0.9
            ))

        return DimensionScore(
            dimension=CriticDimension.RELEVANCE,
            score=max(0.0, min(1.0, relevance_score)),
            issues=issues,
            reasoning=f"Query-answer term overlap: {overlap}/{len(query_terms)}"
        )

    def _evaluate_completeness(self, query: str, answer: str) -> DimensionScore:
        """Evaluate if answer is complete."""
        issues = []
        score = 1.0

        # Check for incomplete markers
        if self.patterns["incomplete"].search(answer):
            issues.append(CriticIssue(
                dimension=CriticDimension.COMPLETENESS,
                severity=CriticSeverity.MEDIUM,
                description="Answer appears incomplete (ends with '...' or 'etc.')",
                suggestion="Complete the answer or remove trailing markers",
                confidence=0.9
            ))
            score -= 0.2

        # Check answer length
        min_length = 50 if self._is_simple_query(query) else 150
        if len(answer.strip()) < min_length:
            issues.append(CriticIssue(
                dimension=CriticDimension.COMPLETENESS,
                severity=CriticSeverity.MEDIUM,
                description="Answer may be too brief",
                suggestion="Provide more detailed explanation",
                confidence=0.6
            ))
            score -= 0.3

        # Check if answer addresses all parts of multi-part query
        if " and " in query or "," in query:
            query_parts = re.split(r'\s+and\s+|,\s*', query)
            if len(query_parts) > 1:
                parts_addressed = sum(
                    1 for part in query_parts
                    if any(word in answer.lower() for word in part.lower().split())
                )
                if parts_addressed < len(query_parts):
                    issues.append(CriticIssue(
                        dimension=CriticDimension.COMPLETENESS,
                        severity=CriticSeverity.HIGH,
                        description=f"Only {parts_addressed}/{len(query_parts)} query parts addressed",
                        suggestion="Address all parts of the multi-part query",
                        confidence=0.7
                    ))
                    score *= parts_addressed / len(query_parts)

        return DimensionScore(
            dimension=CriticDimension.COMPLETENESS,
            score=max(0.0, min(1.0, score)),
            issues=issues,
            reasoning=f"Answer length: {len(answer)} chars"
        )

    def _evaluate_coherence(self, answer: str) -> DimensionScore:
        """Evaluate answer coherence and flow."""
        issues = []
        score = 1.0

        sentences = [s.strip() for s in answer.split('.') if s.strip()]

        # Check for very short or very long sentences
        for i, sentence in enumerate(sentences):
            if len(sentence) < 10:
                issues.append(CriticIssue(
                    dimension=CriticDimension.COHERENCE,
                    severity=CriticSeverity.LOW,
                    description="Very short sentence may disrupt flow",
                    location=sentence,
                    confidence=0.5
                ))
                score -= 0.05
            elif len(sentence) > 300:
                issues.append(CriticIssue(
                    dimension=CriticDimension.COHERENCE,
                    severity=CriticSeverity.LOW,
                    description="Very long sentence may be hard to follow",
                    location=sentence[:100] + "...",
                    suggestion="Consider breaking into smaller sentences",
                    confidence=0.6
                ))
                score -= 0.05

        # Check for discourse markers (however, therefore, etc.)
        discourse_markers = ["however", "therefore", "furthermore", "moreover", "additionally"]
        has_markers = any(marker in answer.lower() for marker in discourse_markers)
        if len(sentences) > 3 and not has_markers:
            issues.append(CriticIssue(
                dimension=CriticDimension.COHERENCE,
                severity=CriticSeverity.INFO,
                description="Answer lacks discourse markers for better flow",
                suggestion="Consider adding transitions between ideas",
                confidence=0.4
            ))

        return DimensionScore(
            dimension=CriticDimension.COHERENCE,
            score=max(0.0, min(1.0, score)),
            issues=issues,
            reasoning=f"Analyzed {len(sentences)} sentences"
        )

    def _evaluate_citations(
        self,
        answer: str,
        retrieved_docs: List[Dict[str, Any]]
    ) -> DimensionScore:
        """Evaluate quality of citations."""
        issues = []

        if not self.config.check_citations:
            return DimensionScore(
                dimension=CriticDimension.CITATION,
                score=1.0,
                issues=[],
                reasoning="Citation checking disabled"
            )

        # Check for citation markers
        citations = self.patterns["citation"].findall(answer)

        score = 1.0

        if len(retrieved_docs) > 0 and len(citations) == 0:
            issues.append(CriticIssue(
                dimension=CriticDimension.CITATION,
                severity=CriticSeverity.MEDIUM,
                description="No citations found despite using retrieved documents",
                suggestion="Add citations to attribute information to sources",
                confidence=0.8
            ))
            score = 0.5

        # Check for citation-document mismatch
        # Extract citation numbers
        citation_numbers = re.findall(r'\[(\d+)\]|\((\d+)\)', answer)
        max_citation = max(
            (int(n[0] or n[1]) for n in citation_numbers),
            default=0
        )

        if max_citation > len(retrieved_docs):
            issues.append(CriticIssue(
                dimension=CriticDimension.CITATION,
                severity=CriticSeverity.CRITICAL,
                description=f"Citation [{max_citation}] exceeds number of documents ({len(retrieved_docs)})",
                suggestion="Ensure all citations reference valid documents",
                confidence=1.0
            ))
            score = 0.3

        return DimensionScore(
            dimension=CriticDimension.CITATION,
            score=score,
            issues=issues,
            reasoning=f"Found {len(citations)} citations, {len(retrieved_docs)} documents"
        )

    def _evaluate_hallucination(
        self,
        answer: str,
        retrieved_docs: List[Dict[str, Any]]
    ) -> DimensionScore:
        """Detect potential hallucinations."""
        issues = []

        if not self.config.check_hallucinations:
            return DimensionScore(
                dimension=CriticDimension.HALLUCINATION,
                score=1.0,
                issues=[],
                reasoning="Hallucination checking disabled"
            )

        score = 1.0

        # Check for overly definitive statements
        definitive_matches = self.patterns["definitive"].findall(answer)
        if len(definitive_matches) > 3:
            issues.append(CriticIssue(
                dimension=CriticDimension.HALLUCINATION,
                severity=CriticSeverity.MEDIUM,
                description="Multiple definitive statements may indicate overconfidence",
                suggestion="Verify definitive claims against sources",
                evidence=f"Found terms: {', '.join(definitive_matches[:3])}",
                confidence=0.6
            ))
            score -= 0.2

        # Check for specific numbers/dates not in retrieved docs
        numbers = re.findall(r'\b\d{4}\b|\b\d+\.\d+\b|\b\d+%\b', answer)
        if numbers:
            doc_texts = " ".join([doc.get("document", "") for doc in retrieved_docs])
            unsupported_numbers = [n for n in numbers if n not in doc_texts]

            if len(unsupported_numbers) > 0:
                issues.append(CriticIssue(
                    dimension=CriticDimension.HALLUCINATION,
                    severity=CriticSeverity.HIGH,
                    description="Specific numbers/dates not found in source documents",
                    evidence=f"Unsupported: {', '.join(unsupported_numbers[:3])}",
                    suggestion="Verify all numerical claims against sources",
                    confidence=0.7
                ))
                score -= 0.3

        return DimensionScore(
            dimension=CriticDimension.HALLUCINATION,
            score=max(0.0, min(1.0, score)),
            issues=issues,
            reasoning=f"Checked {len(numbers)} numerical claims"
        )

    def _evaluate_consistency(self, answer: str) -> DimensionScore:
        """Evaluate internal consistency."""
        issues = []
        score = 1.0

        sentences = [s.strip() for s in answer.split('.') if s.strip()]

        # Check for contradictory statements (simple heuristic)
        contradiction_pairs = [
            ("yes", "no"),
            ("always", "never"),
            ("increase", "decrease"),
            ("true", "false")
        ]

        answer_lower = answer.lower()
        for word1, word2 in contradiction_pairs:
            if word1 in answer_lower and word2 in answer_lower:
                # Check if they're in different contexts (very simple check)
                issues.append(CriticIssue(
                    dimension=CriticDimension.CONSISTENCY,
                    severity=CriticSeverity.MEDIUM,
                    description=f"Potential contradiction: contains both '{word1}' and '{word2}'",
                    suggestion="Review for internal consistency",
                    confidence=0.5
                ))
                score -= 0.1

        return DimensionScore(
            dimension=CriticDimension.CONSISTENCY,
            score=max(0.0, min(1.0, score)),
            issues=issues,
            reasoning="Checked for common contradiction patterns"
        )

    def _generate_recommendations(
        self,
        dimension_scores: List[DimensionScore]
    ) -> List[str]:
        """Generate actionable recommendations."""
        recommendations = []

        # Priority recommendations based on critical issues
        for ds in dimension_scores:
            critical_issues = [i for i in ds.issues if i.severity == CriticSeverity.CRITICAL]
            if critical_issues:
                recommendations.append(
                    f"CRITICAL: Fix {ds.dimension.value} issues - "
                    f"{critical_issues[0].description}"
                )

        # Recommendations based on low scores
        low_scores = [ds for ds in dimension_scores if ds.score < 0.5]
        for ds in low_scores:
            recommendations.append(
                f"Improve {ds.dimension.value} (score: {ds.score:.2f}) - "
                f"{ds.reasoning}"
            )

        # General recommendations
        if not recommendations:
            high_score_dims = [ds for ds in dimension_scores if ds.score >= 0.8]
            if high_score_dims:
                recommendations.append(
                    "Good quality overall. Minor improvements possible in: " +
                    ", ".join([ds.dimension.value for ds in dimension_scores if ds.score < 0.8])
                )

        return recommendations[:5]  # Top 5 recommendations

    def _extract_query_type(self, query: str) -> Optional[str]:
        """Extract query type (what, how, why, etc.)."""
        query_lower = query.lower()
        for qtype in ["what", "how", "why", "when", "where", "who", "which"]:
            if query_lower.startswith(qtype):
                return qtype
        return None

    def _answer_matches_query_type(self, answer: str, query_type: str) -> bool:
        """Check if answer matches query type."""
        answer_lower = answer.lower()

        # Simple heuristics for query type matching
        if query_type == "when" and not re.search(r'\b\d{4}\b|today|yesterday|ago', answer_lower):
            return False
        if query_type == "where" and not re.search(r'\bin\s+|at\s+|near\s+', answer_lower):
            return False
        if query_type == "how" and not re.search(r'\bby\s+|through\s+|using\s+', answer_lower):
            return False

        return True

    def _is_simple_query(self, query: str) -> bool:
        """Check if query is simple (short answer expected)."""
        simple_indicators = ["what is", "who is", "when was", "where is"]
        return any(query.lower().startswith(ind) for ind in simple_indicators)

    def get_stats(self) -> Dict[str, Any]:
        """Get critic statistics."""
        return self.stats.copy()

    def reset_stats(self):
        """Reset statistics."""
        self.stats = {
            "total_critiques": 0,
            "average_score": 0.0,
            "critical_issues_found": 0
        }
