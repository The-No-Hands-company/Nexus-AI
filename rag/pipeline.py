"""
Production-grade RAG Pipeline integrating all components.

Complete end-to-end RAG workflow:
1. Query Decomposition
2. Planning
3. Adaptive Retrieval
4. Reranking & Filtering
5. Synthesis
6. Critique & Validation
7. Iterative Refinement
"""

from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import time
import logging

logger = logging.getLogger(__name__)

from .query_decomposer import QueryDecomposer, DecompositionResult
from .planner import PlannerAgent, Plan, PlanStep, StepType, StepStatus
from .critic import CriticAgent, Critique, CriticConfig, CriticDimension
from .retriever import AdaptiveRetriever, RetrieverConfig, RetrievalResult
from .vector_store import VectorStore, VectorStoreConfig
from .embeddings import EmbeddingModel, EmbeddingConfig


class PipelineStage(Enum):
    """RAG pipeline stages."""
    DECOMPOSITION = "decomposition"
    PLANNING = "planning"
    RETRIEVAL = "retrieval"
    SYNTHESIS = "synthesis"
    CRITIQUE = "critique"
    REFINEMENT = "refinement"


@dataclass
class RAGConfig:
    """Configuration for RAG pipeline."""
    
    # Component configs
    embedding_config: Optional[EmbeddingConfig] = None
    vector_store_config: Optional[VectorStoreConfig] = None
    retriever_config: Optional[RetrieverConfig] = None
    critic_config: Optional[CriticConfig] = None
    
    # Pipeline behavior
    enable_decomposition: bool = True
    enable_planning: bool = True
    enable_critique: bool = True
    enable_refinement: bool = True
    
    # Quality thresholds
    min_acceptable_score: float = 0.7
    max_refinement_iterations: int = 3
    
    # Performance
    cache_results: bool = True
    parallel_retrieval: bool = True


@dataclass
class RAGResult:
    """Result from RAG pipeline."""
    
    query: str
    answer: str
    retrieved_documents: List[Dict[str, Any]]
    sources: List[str]
    
    # Metadata
    decomposition: Optional[DecompositionResult] = None
    plan: Optional[Plan] = None
    critique: Optional[Critique] = None
    
    confidence_score: float = 0.0
    execution_time: float = 0.0
    stage_times: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query": self.query,
            "answer": self.answer,
            "sources": self.sources,
            "confidence_score": self.confidence_score,
            "execution_time": self.execution_time,
            "stage_times": self.stage_times,
            "num_documents": len(self.retrieved_documents),
            "critique_score": self.critique.overall_score if self.critique else None,
            "timestamp": self.timestamp,
            "metadata": self.metadata
        }


class RAGPipeline:
    """
    Production-grade RAG pipeline with full workflow.
    
    Workflow:
    1. Query Decomposition (optional, for complex queries)
    2. Execution Planning
    3. Adaptive Retrieval with reranking
    4. Answer Synthesis
    5. Quality Critique
    6. Iterative Refinement (if needed)
    
    Features:
    - Modular component architecture
    - Adaptive strategy selection
    - Quality assurance with critique
    - Performance monitoring
    - Caching and optimization
    """
    
    def __init__(
        self,
        config: Optional[RAGConfig] = None,
        llm_model: Optional[Any] = None
    ):
        """
        Initialize RAG pipeline.
        
        Args:
            config: Pipeline configuration
            llm_model: LLM model for synthesis and optional components
        """
        self.config = config or RAGConfig()
        self.llm_model = llm_model
        
        # Initialize components
        self._init_components()
        
        # Statistics
        self.stats = {
            "total_queries": 0,
            "successful_queries": 0,
            "failed_queries": 0,
            "average_time": 0.0,
            "average_score": 0.0,
            "refinements_triggered": 0
        }
        
        # Cache
        self._cache: Dict[str, RAGResult] = {}
        
        if HAS_CPP_LOGGER:
            CPPLogger.info("RAGPipeline initialized", "RAGPipeline")
        else:
            CPPLogger.info("RAGPipeline initialized")
    
    def _init_components(self):
        """Initialize pipeline components."""
        # Embedding model
        self.embedding_model = EmbeddingModel(
            self.config.embedding_config or EmbeddingConfig()
        )
        
        # Vector store
        self.vector_store = VectorStore(
            self.config.vector_store_config or VectorStoreConfig(),
            self.embedding_model
        )
        
        # Retriever
        self.retriever = AdaptiveRetriever(
            self.vector_store,
            self.embedding_model,
            self.config.retriever_config or RetrieverConfig()
        )
        
        # Query decomposer
        if self.config.enable_decomposition:
            self.decomposer = QueryDecomposer(
                use_llm=bool(self.llm_model),
                llm_model=self.llm_model
            )
        else:
            self.decomposer = None
        
        # Planner
        if self.config.enable_planning:
            self.planner = PlannerAgent(
                use_llm=bool(self.llm_model),
                llm_model=self.llm_model
            )
        else:
            self.planner = None
        
        # Critic
        if self.config.enable_critique:
            self.critic = CriticAgent(
                self.config.critic_config or CriticConfig()
            )
        else:
            self.critic = None
    
    def query(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        callbacks: Optional[Dict[PipelineStage, Callable]] = None
    ) -> RAGResult:
        """
        Execute complete RAG pipeline for a query.
        
        Args:
            query: User query
            context: Optional additional context
            callbacks: Optional callbacks for each stage
            
        Returns:
            RAGResult with answer and metadata
        """
        start_time = time.time()
        stage_times = {}
        
        if HAS_CPP_LOGGER:
            CPPLogger.info(f"Processing query: {query[:100]}...", "RAGPipeline")
        else:
            CPPLogger.info(f"Processing query: {query[:100]}...")
        
        # Check cache
        if self.config.cache_results and query in self._cache:
            if HAS_CPP_LOGGER:
                CPPLogger.debug("Returning cached result", "RAGPipeline")
            cached_result = self._cache[query]
            return cached_result
        
        try:
            # Stage 1: Query Decomposition
            decomposition = None
            if self.config.enable_decomposition and self.decomposer:
                stage_start = time.time()
                decomposition = self.decomposer.decompose(query)
                stage_times[PipelineStage.DECOMPOSITION.value] = time.time() - stage_start
                
                if callbacks and PipelineStage.DECOMPOSITION in callbacks:
                    callbacks[PipelineStage.DECOMPOSITION](decomposition)
            
            # Stage 2: Planning
            plan = None
            if self.config.enable_planning and self.planner:
                stage_start = time.time()
                plan = self.planner.create_plan(query, decomposition, context)
                stage_times[PipelineStage.PLANNING.value] = time.time() - stage_start
                
                if callbacks and PipelineStage.PLANNING in callbacks:
                    callbacks[PipelineStage.PLANNING](plan)
            
            # Stage 3: Retrieval
            stage_start = time.time()
            retrieval_result = self.retriever.retrieve(
                query,
                decomposition_result=decomposition
            )
            stage_times[PipelineStage.RETRIEVAL.value] = time.time() - stage_start
            
            if callbacks and PipelineStage.RETRIEVAL in callbacks:
                callbacks[PipelineStage.RETRIEVAL](retrieval_result)
            
            # Stage 4: Synthesis
            stage_start = time.time()
            answer = self._synthesize_answer(query, retrieval_result, context)
            stage_times[PipelineStage.SYNTHESIS.value] = time.time() - stage_start
            
            if callbacks and PipelineStage.SYNTHESIS in callbacks:
                callbacks[PipelineStage.SYNTHESIS](answer)
            
            # Stage 5: Critique
            critique = None
            if self.config.enable_critique and self.critic:
                stage_start = time.time()
                critique = self.critic.critique(
                    query,
                    answer,
                    retrieval_result.documents,
                    context
                )
                stage_times[PipelineStage.CRITIQUE.value] = time.time() - stage_start
                
                if callbacks and PipelineStage.CRITIQUE in callbacks:
                    callbacks[PipelineStage.CRITIQUE](critique)
            
            # Stage 6: Refinement (if needed)
            refinement_count = 0
            if (self.config.enable_refinement and critique and
                not critique.is_acceptable(self.config.min_acceptable_score) and
                refinement_count < self.config.max_refinement_iterations):
                
                stage_start = time.time()
                answer, refinement_count = self._refine_answer(
                    query,
                    answer,
                    retrieval_result,
                    critique,
                    context
                )
                stage_times[PipelineStage.REFINEMENT.value] = time.time() - stage_start
                
                # Re-critique refined answer
                if self.critic:
                    critique = self.critic.critique(
                        query,
                        answer,
                        retrieval_result.documents,
                        context
                    )
                
                if callbacks and PipelineStage.REFINEMENT in callbacks:
                    callbacks[PipelineStage.REFINEMENT]((answer, refinement_count))
                
                self.stats["refinements_triggered"] += 1
            
            # Extract sources
            sources = self._extract_sources(retrieval_result)
            
            # Create result
            result = RAGResult(
                query=query,
                answer=answer,
                retrieved_documents=retrieval_result.documents,
                sources=sources,
                decomposition=decomposition,
                plan=plan,
                critique=critique,
                confidence_score=critique.overall_score if critique else 0.8,
                execution_time=time.time() - start_time,
                stage_times=stage_times,
                metadata={
                    "retrieval_strategy": retrieval_result.strategy_used.value,
                    "num_documents": len(retrieval_result.documents),
                    "refinement_iterations": refinement_count,
                    "context_provided": context is not None
                }
            )
            
            # Update statistics
            self.stats["total_queries"] += 1
            self.stats["successful_queries"] += 1
            self.stats["average_time"] = (
                (self.stats["average_time"] * (self.stats["total_queries"] - 1) +
                 result.execution_time) / self.stats["total_queries"]
            )
            if critique:
                self.stats["average_score"] = (
                    (self.stats["average_score"] * (self.stats["successful_queries"] - 1) +
                     critique.overall_score) / self.stats["successful_queries"]
                )
            
            # Cache result
            if self.config.cache_results:
                self._cache[query] = result
            
            if HAS_CPP_LOGGER:
                CPPLogger.info(
                    f"Query processed successfully in {result.execution_time:.2f}s "
                    f"(score: {result.confidence_score:.2f})",
                    "RAGPipeline"
                )
            else:
                CPPLogger.info(
                    f"Query processed successfully in {result.execution_time:.2f}s "
                    f"(score: {result.confidence_score:.2f})"
                )
            
            return result
            
        except Exception as e:
            self.stats["total_queries"] += 1
            self.stats["failed_queries"] += 1
            
            if HAS_CPP_LOGGER:
                CPPLogger.error(f"Pipeline failed: {e}", "RAGPipeline")
            else:
                CPPLogger.error(f"Pipeline failed: {e}")
            
            # Return error result
            return RAGResult(
                query=query,
                answer=f"Error processing query: {str(e)}",
                retrieved_documents=[],
                sources=[],
                confidence_score=0.0,
                execution_time=time.time() - start_time,
                metadata={"error": str(e)}
            )
    
    def _synthesize_answer(
        self,
        query: str,
        retrieval_result: RetrievalResult,
        context: Optional[Dict[str, Any]]
    ) -> str:
        """Synthesize answer from retrieved documents."""
        if not retrieval_result.documents:
            return "I don't have enough information to answer this question."
        
        # Prepare context from retrieved documents
        doc_context = "\n\n".join([
            f"[{i+1}] {doc['document']}"
            for i, doc in enumerate(retrieval_result.documents)
        ])
        
        # Build synthesis prompt
        prompt = f"""Based on the following context, answer the question.

Question: {query}

Context:
{doc_context}

Provide a comprehensive answer with citations [1], [2], etc. If the context doesn't contain enough information, say so.

Answer:"""
        
        # Generate answer using LLM
        if self.llm_model:
            try:
                answer = self.llm_model.generate(
                    prompt,
                    max_tokens=500,
                    temperature=0.3
                )
                return answer.strip()
            except Exception as e:
                if HAS_CPP_LOGGER:
                    CPPLogger.error(f"LLM synthesis failed: {e}", "RAGPipeline")
                else:
                    CPPLogger.error(f"LLM synthesis failed: {e}")
        
        # Fallback: extractive summary
        return self._extractive_answer(query, retrieval_result.documents)
    
    def _extractive_answer(self, query: str, documents: List[Dict[str, Any]]) -> str:
        """Create extractive answer from documents (fallback)."""
        # Simple extractive approach: return most relevant sentences
        query_terms = set(query.lower().split())
        
        sentences = []
        for doc in documents[:3]:  # Top 3 documents
            doc_sentences = doc["document"].split('.')
            for sentence in doc_sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                
                sentence_terms = set(sentence.lower().split())
                overlap = len(query_terms & sentence_terms)
                if overlap >= 2:  # At least 2 matching terms
                    sentences.append(sentence)
        
        if sentences:
            return ". ".join(sentences[:3]) + "."
        else:
            return "Based on the available information: " + documents[0]["document"][:200] + "..."
    
    def _refine_answer(
        self,
        query: str,
        answer: str,
        retrieval_result: RetrievalResult,
        critique: Critique,
        context: Optional[Dict[str, Any]]
    ) -> tuple[str, int]:
        """Refine answer based on critique."""
        refinement_count = 0
        current_answer = answer
        
        for iteration in range(self.config.max_refinement_iterations):
            # Build refinement prompt based on critique
            issues_text = "\n".join([
                f"- {issue.description}: {issue.suggestion or 'Please address this issue'}"
                for issue in critique.get_critical_issues()[:3]
            ])
            
            if not issues_text:
                break
            
            prompt = f"""Improve the following answer based on the critique.

Original Question: {query}

Current Answer:
{current_answer}

Issues to Address:
{issues_text}

Provide an improved answer that addresses these issues:"""
            
            if self.llm_model:
                try:
                    refined_answer = self.llm_model.generate(
                        prompt,
                        max_tokens=500,
                        temperature=0.2
                    )
                    current_answer = refined_answer.strip()
                    refinement_count += 1
                    
                    # Re-critique
                    new_critique = self.critic.critique(
                        query,
                        current_answer,
                        retrieval_result.documents
                    )
                    
                    # Check if acceptable
                    if new_critique.is_acceptable(self.config.min_acceptable_score):
                        break
                    
                    critique = new_critique
                    
                except Exception as e:
                    if HAS_CPP_LOGGER:
                        CPPLogger.error(f"Refinement failed: {e}", "RAGPipeline")
                    else:
                        CPPLogger.error(f"Refinement failed: {e}")
                    break
            else:
                break
        
        return current_answer, refinement_count
    
    def _extract_sources(self, retrieval_result: RetrievalResult) -> List[str]:
        """Extract source citations from retrieved documents."""
        sources = []
        for i, doc in enumerate(retrieval_result.documents, 1):
            metadata = doc.get("metadata", {})
            source = metadata.get("source", f"Document {i}")
            sources.append(f"[{i}] {source}")
        return sources
    
    def add_documents(
        self,
        documents: List[str],
        metadata: Optional[List[Dict[str, Any]]] = None,
        batch_size: int = 100
    ) -> List[str]:
        """
        Add documents to the vector store.
        
        Args:
            documents: List of document texts
            metadata: Optional metadata for each document
            batch_size: Batch size for processing
            
        Returns:
            List of document IDs
        """
        if HAS_CPP_LOGGER:
            CPPLogger.info(f"Adding {len(documents)} documents", "RAGPipeline")
        else:
            CPPLogger.info(f"Adding {len(documents)} documents")
        
        all_ids = []
        
        # Process in batches
        for i in range(0, len(documents), batch_size):
            batch_docs = documents[i:i+batch_size]
            batch_meta = metadata[i:i+batch_size] if metadata else None
            
            ids = self.vector_store.add_documents(
                documents=batch_docs,
                metadata=batch_meta
            )
            all_ids.extend(ids)
        
        if HAS_CPP_LOGGER:
            CPPLogger.info(f"Added {len(all_ids)} documents", "RAGPipeline")
        else:
            CPPLogger.info(f"Added {len(all_ids)} documents")
        
        return all_ids
    
    def get_stats(self) -> Dict[str, Any]:
        """Get pipeline statistics."""
        return {
            **self.stats,
            "cache_size": len(self._cache),
            "vector_store_docs": self.vector_store.count()
        }
    
    def clear_cache(self):
        """Clear result cache."""
        self._cache.clear()
        if HAS_CPP_LOGGER:
            CPPLogger.info("Cache cleared", "RAGPipeline")
        else:
            CPPLogger.info("Cache cleared")
    
    def reset_stats(self):
        """Reset statistics."""
        self.stats = {
            "total_queries": 0,
            "successful_queries": 0,
            "failed_queries": 0,
            "average_time": 0.0,
            "average_score": 0.0,
            "refinements_triggered": 0
        }
