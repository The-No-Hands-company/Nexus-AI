"""
Production-grade Query Decomposer for intelligent multi-hop retrieval.

Features:
- Complex query decomposition into sub-queries
- Dependency tracking between sub-queries
- Temporal awareness (time-sensitive queries)
- Entity extraction and relationship mapping
- Adaptive decomposition based on query complexity
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import re
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class QueryType(Enum):
    """Types of queries for adaptive handling."""
    SIMPLE = "simple"  # Single factual lookup
    COMPLEX = "complex"  # Multiple sub-queries needed
    TEMPORAL = "temporal"  # Time-sensitive query
    COMPARATIVE = "comparative"  # Comparison between entities
    MULTI_HOP = "multi_hop"  # Requires chaining information


@dataclass
class SubQuery:
    """A decomposed sub-query with metadata."""

    text: str
    query_type: QueryType
    dependencies: List[int]  # Indices of sub-queries this depends on
    priority: int = 0  # Higher priority executed first
    temporal_constraint: Optional[str] = None  # e.g., "2023", "last year"
    entities: List[str] = None  # Extracted entities

    def __post_init__(self):
        if self.entities is None:
            self.entities = []


@dataclass
class DecompositionResult:
    """Result of query decomposition."""

    original_query: str
    sub_queries: List[SubQuery]
    query_type: QueryType
    complexity_score: float  # 0.0 (simple) to 1.0 (very complex)
    execution_plan: List[List[int]]  # Stages of sub-query execution
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class QueryDecomposer:
    """
    Production-grade query decomposer for intelligent retrieval.

    Decomposes complex queries into executable sub-queries with:
    - Dependency tracking
    - Temporal awareness
    - Entity extraction
    - Adaptive complexity scoring
    """

    def __init__(self, use_llm: bool = False, llm_model=None):
        """
        Initialize query decomposer.

        Args:
            use_llm: Whether to use LLM for decomposition (higher quality)
            llm_model: Optional LLM model for advanced decomposition
        """
        self.use_llm = use_llm
        self.llm_model = llm_model

        # Pattern matching for heuristic decomposition
        self._init_patterns()

        if HAS_CPP_LOGGER:
            logger.info(
                f"QueryDecomposer initialized (LLM mode: {use_llm})",
                "QueryDecomposer"
            )
        else:
            logger.info(f"QueryDecomposer initialized (LLM mode: {use_llm})")

    def _init_patterns(self):
        """Initialize regex patterns for heuristic decomposition."""
        self.patterns = {
            "conjunction": re.compile(r"\s+and\s+|\s*,\s*", re.IGNORECASE),
            "temporal": re.compile(
                r"\b(in|during|since|before|after|when)\s+(\d{4}|last|recent|current)\b",
                re.IGNORECASE
            ),
            "comparative": re.compile(
                r"\b(compare|versus|vs|difference|similarity)\b",
                re.IGNORECASE
            ),
            "multi_hop": re.compile(
                r"\b(who|what|when|where|why)\s+.*\s+(of|in|for|about)\s+",
                re.IGNORECASE
            ),
            "entity": re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b"),
            "year": re.compile(r"\b(19|20)\d{2}\b")
        }

    def decompose(self, query: str) -> DecompositionResult:
        """
        Decompose query into executable sub-queries.

        Args:
            query: User query to decompose

        Returns:
            DecompositionResult with sub-queries and execution plan
        """
        if HAS_CPP_LOGGER:
            logger.debug(f"Decomposing query: {query[:100]}...", "QueryDecomposer")
        else:
            logger.debug(f"Decomposing query: {query[:100]}...")

        # Determine query type and complexity
        query_type, complexity = self._analyze_query(query)

        # Decompose based on method
        if self.use_llm and self.llm_model:
            sub_queries = self._decompose_with_llm(query, query_type)
        else:
            sub_queries = self._decompose_heuristic(query, query_type)

        # Build execution plan (topological sort based on dependencies)
        execution_plan = self._build_execution_plan(sub_queries)

        result = DecompositionResult(
            original_query=query,
            sub_queries=sub_queries,
            query_type=query_type,
            complexity_score=complexity,
            execution_plan=execution_plan,
            metadata={
                "decomposition_method": "llm" if self.use_llm else "heuristic",
                "timestamp": datetime.now().isoformat()
            }
        )

        if HAS_CPP_LOGGER:
            logger.info(
                f"Decomposed into {len(sub_queries)} sub-queries (complexity: {complexity:.2f})",
                "QueryDecomposer"
            )
        else:
            logger.info(
                f"Decomposed into {len(sub_queries)} sub-queries (complexity: {complexity:.2f})"
            )

        return result

    def _analyze_query(self, query: str) -> Tuple[QueryType, float]:
        """
        Analyze query to determine type and complexity.

        Priority: TEMPORAL > COMPARATIVE > MULTI_HOP > COMPLEX > SIMPLE.
        Complexity accumulates from all matching patterns regardless of
        which type is ultimately selected.

        Returns:
            (QueryType, complexity_score)
        """
        complexity = 0.0
        detected_types: List[QueryType] = []

        # Check for temporal queries
        if self.patterns["temporal"].search(query):
            detected_types.append(QueryType.TEMPORAL)
            complexity += 0.3

        # Check for comparative queries
        if self.patterns["comparative"].search(query):
            detected_types.append(QueryType.COMPARATIVE)
            complexity += 0.4

        # Check for multi-hop reasoning
        if self.patterns["multi_hop"].search(query):
            detected_types.append(QueryType.MULTI_HOP)
            complexity += 0.5

        # Check for conjunctions (multiple parts)
        conjunctions = self.patterns["conjunction"].findall(query)
        if len(conjunctions) > 0:
            detected_types.append(QueryType.COMPLEX)
            complexity += 0.2 * len(conjunctions)

        # Select type by specificity priority
        priority = [
            QueryType.TEMPORAL,
            QueryType.COMPARATIVE,
            QueryType.MULTI_HOP,
            QueryType.COMPLEX,
        ]
        query_type = QueryType.SIMPLE
        for t in priority:
            if t in detected_types:
                query_type = t
                break

        # Normalize complexity to [0, 1]
        complexity = min(1.0, complexity)

        return query_type, complexity

    def _decompose_heuristic(self, query: str, query_type: QueryType) -> List[SubQuery]:
        """
        Decompose query using heuristic rules.

        Fallback method when LLM is not available.
        """
        sub_queries = []

        if query_type == QueryType.SIMPLE:
            # No decomposition needed
            sub_queries.append(SubQuery(
                text=query,
                query_type=QueryType.SIMPLE,
                dependencies=[],
                priority=0,
                entities=self._extract_entities(query)
            ))

        elif query_type == QueryType.TEMPORAL:
            # Extract temporal constraint and create sub-query
            temporal_match = self.patterns["temporal"].search(query)
            temporal_constraint = temporal_match.group(0) if temporal_match else None

            sub_queries.append(SubQuery(
                text=query,
                query_type=QueryType.TEMPORAL,
                dependencies=[],
                priority=0,
                temporal_constraint=temporal_constraint,
                entities=self._extract_entities(query)
            ))

        elif query_type == QueryType.COMPARATIVE:
            # Split into comparison parts
            parts = self.patterns["comparative"].split(query)
            if len(parts) >= 3:
                # Extract entities being compared
                entities = self._extract_entities(query)

                # Create sub-queries for each entity
                for i, entity in enumerate(entities[:2]):  # Compare first two entities
                    sub_queries.append(SubQuery(
                        text=f"Information about {entity}",
                        query_type=QueryType.SIMPLE,
                        dependencies=[],
                        priority=1,
                        entities=[entity]
                    ))

                # Final comparison query
                sub_queries.append(SubQuery(
                    text=query,
                    query_type=QueryType.COMPARATIVE,
                    dependencies=list(range(len(entities[:2]))),
                    priority=0,
                    entities=entities
                ))
            else:
                # Fallback to simple
                sub_queries.append(SubQuery(
                    text=query,
                    query_type=QueryType.COMPARATIVE,
                    dependencies=[],
                    priority=0,
                    entities=self._extract_entities(query)
                ))

        elif query_type == QueryType.COMPLEX:
            # Split on conjunctions
            parts = self.patterns["conjunction"].split(query)
            for i, part in enumerate(parts):
                part = part.strip()
                if part:
                    sub_queries.append(SubQuery(
                        text=part,
                        query_type=QueryType.SIMPLE,
                        dependencies=[],
                        priority=0,
                        entities=self._extract_entities(part)
                    ))

        elif query_type == QueryType.MULTI_HOP:
            # Extract components for multi-hop reasoning
            # Example: "Who is the CEO of the company that created ChatGPT?"
            # -> Sub-query 1: "What company created ChatGPT?"
            # -> Sub-query 2: "Who is the CEO of [result from 1]?"

            # For heuristic, create a simplified version
            sub_queries.append(SubQuery(
                text=query,
                query_type=QueryType.MULTI_HOP,
                dependencies=[],
                priority=0,
                entities=self._extract_entities(query)
            ))

        return sub_queries if sub_queries else [SubQuery(
            text=query,
            query_type=QueryType.SIMPLE,
            dependencies=[],
            priority=0,
            entities=self._extract_entities(query)
        )]

    def _decompose_with_llm(self, query: str, query_type: QueryType) -> List[SubQuery]:
        """
        Decompose query using LLM for high-quality decomposition.

        Args:
            query: Query to decompose
            query_type: Detected query type

        Returns:
            List of sub-queries with dependencies
        """
        prompt = self._build_decomposition_prompt(query, query_type)

        try:
            response = self.llm_model.generate(
                prompt,
                max_tokens=500,
                temperature=0.3  # Lower temperature for more structured output
            )

            # Parse LLM response into SubQuery objects
            sub_queries = self._parse_llm_decomposition(response, query_type)
            return sub_queries

        except Exception as e:
            if HAS_CPP_LOGGER:
                logger.error(
                    f"LLM decomposition failed, falling back to heuristic: {e}",
                    "QueryDecomposer"
                )
            else:
                logger.error(f"LLM decomposition failed, falling back to heuristic: {e}")

            # Fallback to heuristic
            return self._decompose_heuristic(query, query_type)

    def _build_decomposition_prompt(self, query: str, query_type: QueryType) -> str:
        """Build prompt for LLM-based decomposition."""
        prompt = f"""Decompose the following query into sub-queries for efficient retrieval.

Query: {query}
Query Type: {query_type.value}

For each sub-query, provide:
1. The sub-query text
2. Dependencies (indices of sub-queries it depends on)
3. Priority (0=low, 1=high)

Format your response as:
SubQuery 1: [text] | Dependencies: [] | Priority: 1
SubQuery 2: [text] | Dependencies: [1] | Priority: 0

Sub-queries:
"""
        return prompt

    def _parse_llm_decomposition(
        self,
        response: str,
        query_type: QueryType
    ) -> List[SubQuery]:
        """Parse LLM response into SubQuery objects."""
        sub_queries = []

        lines = response.strip().split('\n')
        for line in lines:
            if not line.strip() or not line.startswith("SubQuery"):
                continue

            try:
                # Parse format: "SubQuery N: text | Dependencies: [1,2] | Priority: 0"
                parts = line.split('|')
                text = parts[0].split(':', 1)[1].strip()

                deps_str = parts[1].split(':', 1)[1].strip()
                dependencies = []
                if deps_str != '[]':
                    dependencies = [int(x.strip()) for x in deps_str[1:-1].split(',')]

                priority = int(parts[2].split(':', 1)[1].strip())

                sub_queries.append(SubQuery(
                    text=text,
                    query_type=query_type,
                    dependencies=dependencies,
                    priority=priority,
                    entities=self._extract_entities(text)
                ))

            except Exception as e:
                if HAS_CPP_LOGGER:
                    logger.warning(f"Failed to parse sub-query: {line} - {e}", "QueryDecomposer")
                else:
                    logger.warning(f"Failed to parse sub-query: {line} - {e}")
                continue

        return sub_queries

    def _extract_entities(self, text: str) -> List[str]:
        """Extract named entities from text (simple pattern-based)."""
        entities = self.patterns["entity"].findall(text)
        # Filter out common non-entities
        stopwords = {"What", "When", "Where", "Who", "Why", "How", "The", "A", "An"}
        return [e for e in entities if e not in stopwords]

    def _build_execution_plan(self, sub_queries: List[SubQuery]) -> List[List[int]]:
        """
        Build execution plan using topological sort.

        Returns list of stages, where each stage contains indices of
        sub-queries that can be executed in parallel.
        """
        if not sub_queries:
            return []

        # Build dependency graph
        num_queries = len(sub_queries)
        in_degree = [0] * num_queries

        for i, sq in enumerate(sub_queries):
            in_degree[i] = len(sq.dependencies)

        # Topological sort (Kahn's algorithm)
        execution_plan = []
        executed = set()

        while len(executed) < num_queries:
            # Find all queries with no remaining dependencies
            current_stage = []
            for i in range(num_queries):
                if i not in executed and in_degree[i] == 0:
                    current_stage.append(i)

            if not current_stage:
                # Circular dependency or error, add remaining queries
                current_stage = [i for i in range(num_queries) if i not in executed]

            execution_plan.append(current_stage)

            # Mark as executed and update dependencies
            for i in current_stage:
                executed.add(i)
                # Reduce in-degree for dependent queries
                for j in range(num_queries):
                    if i in sub_queries[j].dependencies:
                        in_degree[j] -= 1

        return execution_plan

    def visualize_plan(self, result: DecompositionResult) -> str:
        """
        Create a human-readable visualization of the execution plan.

        Args:
            result: DecompositionResult to visualize

        Returns:
            Formatted string representation
        """
        lines = [
            f"Query: {result.original_query}",
            f"Type: {result.query_type.value}",
            f"Complexity: {result.complexity_score:.2f}",
            f"Sub-queries: {len(result.sub_queries)}",
            "",
            "Execution Plan:"
        ]

        for stage_idx, stage in enumerate(result.execution_plan, 1):
            lines.append(f"\nStage {stage_idx}:")
            for sq_idx in stage:
                sq = result.sub_queries[sq_idx]
                deps = f" (depends on: {sq.dependencies})" if sq.dependencies else ""
                lines.append(f"  {sq_idx + 1}. {sq.text}{deps}")

        return "\n".join(lines)
