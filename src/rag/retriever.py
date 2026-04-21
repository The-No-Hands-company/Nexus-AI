"""
Production-grade Adaptive Retriever with multiple strategies.

Features:
- Dense retrieval (vector similarity)
- Sparse retrieval (BM25)
- Hybrid retrieval (dense + sparse)
- Reranking (cross-encoder)
- Query expansion
- Multi-hop retrieval
- Contextual compression
"""

from typing import List, Dict, Any, Optional, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum
import numpy as np
import logging

logger = logging.getLogger(__name__)
from .logging_compat import HAS_CPP_LOGGER


class RetrievalStrategy(Enum):
    """Retrieval strategies."""
    DENSE = "dense"  # Vector similarity only
    SPARSE = "sparse"  # BM25/keyword only
    HYBRID = "hybrid"  # Dense + sparse fusion
    MULTI_HOP = "multi_hop"  # Multi-hop reasoning
    ADAPTIVE = "adaptive"  # Automatically choose best strategy


class RerankMethod(Enum):
    """Reranking methods."""
    NONE = "none"
    CROSS_ENCODER = "cross_encoder"
    LLM = "llm"
    MMR = "mmr"  # Maximal Marginal Relevance


@dataclass
class RetrieverConfig:
    """Configuration for adaptive retriever."""
    
    strategy: RetrievalStrategy = RetrievalStrategy.HYBRID
    top_k: int = 10
    rerank_top_k: int = 5
    rerank_method: RerankMethod = RerankMethod.CROSS_ENCODER
    
    # Dense retrieval params
    dense_weight: float = 0.7
    use_query_expansion: bool = True
    
    # Sparse retrieval params
    sparse_weight: float = 0.3
    bm25_k1: float = 1.5
    bm25_b: float = 0.75
    
    # Reranking params
    cross_encoder_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    
    # Diversity params
    use_mmr: bool = True
    mmr_lambda: float = 0.5  # 0=diversity, 1=relevance
    
    # Compression
    use_compression: bool = True
    max_tokens_per_doc: int = 500


@dataclass
class RetrievalResult:
    """Result from retrieval operation."""
    
    documents: List[Dict[str, Any]]
    scores: List[float]
    strategy_used: RetrievalStrategy
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def get_top_k(self, k: int) -> "RetrievalResult":
        """Get top k documents."""
        return RetrievalResult(
            documents=self.documents[:k],
            scores=self.scores[:k],
            strategy_used=self.strategy_used,
            metadata=self.metadata
        )


class AdaptiveRetriever:
    """
    Production-grade adaptive retriever with multiple strategies.
    
    Capabilities:
    - Dense vector similarity search
    - Sparse BM25 keyword search
    - Hybrid retrieval with score fusion
    - Cross-encoder reranking
    - MMR for diversity
    - Query expansion
    - Multi-hop retrieval
    - Contextual compression
    """
    
    def __init__(
        self,
        vector_store,
        embedding_model,
        config: Optional[RetrieverConfig] = None
    ):
        """
        Initialize adaptive retriever.
        
        Args:
            vector_store: VectorStore instance
            embedding_model: EmbeddingModel instance
            config: Retriever configuration
        """
        self.vector_store = vector_store
        self.embedding_model = embedding_model
        self.config = config or RetrieverConfig()
        
        # Initialize components
        self.sparse_retriever = None
        self.reranker = None
        
        self._init_components()
        
        if HAS_CPP_LOGGER:
            logger.info(
                f"AdaptiveRetriever initialized (strategy: {self.config.strategy.value})",
                "AdaptiveRetriever"
            )
        else:
            logger.info(
                f"AdaptiveRetriever initialized (strategy: {self.config.strategy.value})"
            )
    
    def _init_components(self):
        """Initialize retrieval components."""
        # Initialize sparse retriever (BM25) if needed
        if self.config.strategy in [RetrievalStrategy.SPARSE, RetrievalStrategy.HYBRID]:
            try:
                from rank_bm25 import BM25Okapi
                self.bm25_class = BM25Okapi
                if HAS_CPP_LOGGER:
                    logger.debug("BM25 sparse retriever initialized", "AdaptiveRetriever")
            except ImportError:
                if HAS_CPP_LOGGER:
                    logger.warning(
                        "rank_bm25 not available, sparse retrieval disabled",
                        "AdaptiveRetriever"
                    )
                else:
                    logger.warning("rank_bm25 not available, sparse retrieval disabled")
        
        # Initialize reranker if needed
        if self.config.rerank_method == RerankMethod.CROSS_ENCODER:
            try:
                from sentence_transformers import CrossEncoder
                self.reranker = CrossEncoder(self.config.cross_encoder_model)
                if HAS_CPP_LOGGER:
                    logger.debug("Cross-encoder reranker initialized", "AdaptiveRetriever")
            except ImportError:
                if HAS_CPP_LOGGER:
                    logger.warning(
                        "sentence-transformers not available, reranking disabled",
                        "AdaptiveRetriever"
                    )
                else:
                    logger.warning("sentence-transformers not available, reranking disabled")
    
    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        filter_metadata: Optional[Dict[str, Any]] = None,
        decomposition_result: Optional[Any] = None
    ) -> RetrievalResult:
        """
        Retrieve relevant documents using configured strategy.
        
        Args:
            query: Query text
            top_k: Number of documents to retrieve (uses config if None)
            filter_metadata: Optional metadata filters
            decomposition_result: Optional query decomposition
            
        Returns:
            RetrievalResult with documents and scores
        """
        top_k = top_k or self.config.top_k
        
        if HAS_CPP_LOGGER:
            logger.debug(
                f"Retrieving with strategy: {self.config.strategy.value}, top_k={top_k}",
                "AdaptiveRetriever"
            )
        
        # Apply query expansion if enabled
        if self.config.use_query_expansion:
            expanded_queries = self._expand_query(query)
        else:
            expanded_queries = [query]
        
        # Choose retrieval strategy
        if self.config.strategy == RetrievalStrategy.ADAPTIVE:
            strategy = self._choose_strategy(query, decomposition_result)
        else:
            strategy = self.config.strategy
        
        # Retrieve documents
        if strategy == RetrievalStrategy.DENSE:
            result = self._dense_retrieval(expanded_queries, top_k, filter_metadata)
        elif strategy == RetrievalStrategy.SPARSE:
            result = self._sparse_retrieval(query, top_k, filter_metadata)
        elif strategy == RetrievalStrategy.HYBRID:
            result = self._hybrid_retrieval(query, expanded_queries, top_k, filter_metadata)
        elif strategy == RetrievalStrategy.MULTI_HOP:
            result = self._multi_hop_retrieval(query, decomposition_result, top_k, filter_metadata)
        else:
            # Fallback to dense
            result = self._dense_retrieval(expanded_queries, top_k, filter_metadata)
        
        # Rerank if configured
        if self.config.rerank_method != RerankMethod.NONE:
            result = self._rerank(query, result)
        
        # Apply MMR for diversity if configured
        if self.config.use_mmr:
            result = self._apply_mmr(query, result)
        
        # Compress documents if configured
        if self.config.use_compression:
            result = self._compress_documents(query, result)
        
        # Trim to final top_k
        result = result.get_top_k(self.config.rerank_top_k)
        
        if HAS_CPP_LOGGER:
            logger.info(
                f"Retrieved {len(result.documents)} documents (strategy: {strategy.value})",
                "AdaptiveRetriever"
            )
        
        return result
    
    def _dense_retrieval(
        self,
        queries: List[str],
        top_k: int,
        filter_metadata: Optional[Dict[str, Any]]
    ) -> RetrievalResult:
        """Dense vector similarity retrieval."""
        all_results = []
        
        for query in queries:
            results = self.vector_store.search(
                query=query,
                k=top_k,
                filter_metadata=filter_metadata
            )
            all_results.extend(results)
        
        # Deduplicate by document ID
        seen_ids = set()
        unique_results = []
        for result in all_results:
            if result["id"] not in seen_ids:
                seen_ids.add(result["id"])
                unique_results.append(result)
        
        # Sort by score
        unique_results.sort(key=lambda x: x["score"], reverse=True)
        
        return RetrievalResult(
            documents=[r for r in unique_results[:top_k]],
            scores=[r["score"] for r in unique_results[:top_k]],
            strategy_used=RetrievalStrategy.DENSE,
            metadata={"num_queries": len(queries)}
        )
    
    def _sparse_retrieval(
        self,
        query: str,
        top_k: int,
        filter_metadata: Optional[Dict[str, Any]]
    ) -> RetrievalResult:
        """Sparse BM25 keyword retrieval."""
        if not hasattr(self, 'bm25_class'):
            # Fallback to dense if BM25 not available
            return self._dense_retrieval([query], top_k, filter_metadata)
        
        # Get all documents from vector store
        # Note: This is simplified - in production, maintain separate BM25 index
        all_docs = self._get_all_documents(filter_metadata)
        
        if not all_docs:
            return RetrievalResult(
                documents=[],
                scores=[],
                strategy_used=RetrievalStrategy.SPARSE,
                metadata={"error": "No documents available"}
            )
        
        # Tokenize documents
        tokenized_corpus = [doc["document"].lower().split() for doc in all_docs]
        bm25 = self.bm25_class(tokenized_corpus)
        
        # Tokenize query and get scores
        tokenized_query = query.lower().split()
        scores = bm25.get_scores(tokenized_query)
        
        # Get top-k indices
        top_indices = np.argsort(scores)[-top_k:][::-1]
        
        # Build results
        results = [all_docs[i] for i in top_indices]
        result_scores = [float(scores[i]) for i in top_indices]
        
        return RetrievalResult(
            documents=results,
            scores=result_scores,
            strategy_used=RetrievalStrategy.SPARSE,
            metadata={"corpus_size": len(all_docs)}
        )
    
    def _hybrid_retrieval(
        self,
        query: str,
        expanded_queries: List[str],
        top_k: int,
        filter_metadata: Optional[Dict[str, Any]]
    ) -> RetrievalResult:
        """Hybrid retrieval combining dense and sparse."""
        # Get dense results
        dense_result = self._dense_retrieval(expanded_queries, top_k * 2, filter_metadata)
        
        # Get sparse results
        sparse_result = self._sparse_retrieval(query, top_k * 2, filter_metadata)
        
        # Reciprocal Rank Fusion (RRF)
        fused_scores = {}
        k = 60  # RRF constant
        
        # Add dense scores
        for rank, doc in enumerate(dense_result.documents):
            doc_id = doc["id"]
            fused_scores[doc_id] = fused_scores.get(doc_id, 0) + self.config.dense_weight / (k + rank + 1)
        
        # Add sparse scores
        for rank, doc in enumerate(sparse_result.documents):
            doc_id = doc["id"]
            fused_scores[doc_id] = fused_scores.get(doc_id, 0) + self.config.sparse_weight / (k + rank + 1)
        
        # Create combined results
        all_docs = {doc["id"]: doc for doc in dense_result.documents + sparse_result.documents}
        
        sorted_ids = sorted(fused_scores.keys(), key=lambda x: fused_scores[x], reverse=True)
        
        final_docs = [all_docs[doc_id] for doc_id in sorted_ids[:top_k]]
        final_scores = [fused_scores[doc_id] for doc_id in sorted_ids[:top_k]]
        
        return RetrievalResult(
            documents=final_docs,
            scores=final_scores,
            strategy_used=RetrievalStrategy.HYBRID,
            metadata={
                "dense_results": len(dense_result.documents),
                "sparse_results": len(sparse_result.documents),
                "fusion_method": "RRF"
            }
        )
    
    def _multi_hop_retrieval(
        self,
        query: str,
        decomposition_result: Optional[Any],
        top_k: int,
        filter_metadata: Optional[Dict[str, Any]]
    ) -> RetrievalResult:
        """Multi-hop retrieval for complex queries."""
        if not decomposition_result or not hasattr(decomposition_result, 'sub_queries'):
            # Fallback to hybrid if no decomposition
            return self._hybrid_retrieval(query, [query], top_k, filter_metadata)
        
        all_documents = []
        all_scores = []
        
        # Retrieve for each sub-query
        for sub_query in decomposition_result.sub_queries:
            sub_result = self._hybrid_retrieval(
                sub_query.text,
                [sub_query.text],
                top_k // len(decomposition_result.sub_queries) + 1,
                filter_metadata
            )
            all_documents.extend(sub_result.documents)
            all_scores.extend(sub_result.scores)
        
        # Deduplicate and rerank
        seen_ids = set()
        unique_docs = []
        unique_scores = []
        
        for doc, score in zip(all_documents, all_scores):
            if doc["id"] not in seen_ids:
                seen_ids.add(doc["id"])
                unique_docs.append(doc)
                unique_scores.append(score)
        
        # Sort by score
        sorted_pairs = sorted(
            zip(unique_docs, unique_scores),
            key=lambda x: x[1],
            reverse=True
        )
        
        final_docs = [p[0] for p in sorted_pairs[:top_k]]
        final_scores = [p[1] for p in sorted_pairs[:top_k]]
        
        return RetrievalResult(
            documents=final_docs,
            scores=final_scores,
            strategy_used=RetrievalStrategy.MULTI_HOP,
            metadata={
                "sub_queries": len(decomposition_result.sub_queries),
                "total_retrieved": len(all_documents)
            }
        )
    
    def _rerank(self, query: str, result: RetrievalResult) -> RetrievalResult:
        """Rerank retrieved documents."""
        if self.config.rerank_method == RerankMethod.CROSS_ENCODER and self.reranker:
            # Prepare query-document pairs
            pairs = [[query, doc["document"]] for doc in result.documents]
            
            # Get reranking scores
            rerank_scores = self.reranker.predict(pairs)
            
            # Combine with original scores (weighted)
            combined_scores = [
                0.7 * float(rerank_score) + 0.3 * orig_score
                for rerank_score, orig_score in zip(rerank_scores, result.scores)
            ]
            
            # Sort by combined scores
            sorted_pairs = sorted(
                zip(result.documents, combined_scores),
                key=lambda x: x[1],
                reverse=True
            )
            
            result.documents = [p[0] for p in sorted_pairs]
            result.scores = [p[1] for p in sorted_pairs]
            result.metadata["reranked"] = True
            
        elif self.config.rerank_method == RerankMethod.MMR:
            result = self._apply_mmr(query, result)
        
        return result
    
    def _apply_mmr(self, query: str, result: RetrievalResult) -> RetrievalResult:
        """Apply Maximal Marginal Relevance for diversity."""
        if len(result.documents) <= 1:
            return result
        
        # Get query embedding
        query_embedding = self.embedding_model.embed_text(query)
        
        # Get document embeddings
        doc_embeddings = [
            self.embedding_model.embed_text(doc["document"])
            for doc in result.documents
        ]
        
        # MMR algorithm
        selected_indices = []
        remaining_indices = list(range(len(result.documents)))
        
        # Select first document (highest relevance)
        selected_indices.append(remaining_indices.pop(0))
        
        # Select remaining documents
        while remaining_indices and len(selected_indices) < len(result.documents):
            mmr_scores = []
            
            for idx in remaining_indices:
                # Relevance to query
                relevance = self.embedding_model.similarity(
                    query_embedding,
                    doc_embeddings[idx]
                )
                
                # Max similarity to already selected documents
                max_sim = max(
                    self.embedding_model.similarity(
                        doc_embeddings[idx],
                        doc_embeddings[sel_idx]
                    )
                    for sel_idx in selected_indices
                )
                
                # MMR score
                mmr = self.config.mmr_lambda * relevance - (1 - self.config.mmr_lambda) * max_sim
                mmr_scores.append((idx, mmr))
            
            # Select document with highest MMR
            best_idx, best_score = max(mmr_scores, key=lambda x: x[1])
            selected_indices.append(best_idx)
            remaining_indices.remove(best_idx)
        
        # Reorder documents
        result.documents = [result.documents[i] for i in selected_indices]
        result.scores = [result.scores[i] for i in selected_indices]
        result.metadata["mmr_applied"] = True
        
        return result
    
    def _compress_documents(self, query: str, result: RetrievalResult) -> RetrievalResult:
        """Compress documents to most relevant passages."""
        compressed_docs = []
        
        for doc in result.documents:
            # Split into sentences
            sentences = doc["document"].split('.')
            
            # Rank sentences by relevance to query
            query_terms = set(query.lower().split())
            sentence_scores = []
            
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                
                sentence_terms = set(sentence.lower().split())
                overlap = len(query_terms & sentence_terms)
                score = overlap / len(query_terms) if query_terms else 0
                sentence_scores.append((sentence, score))
            
            # Select top sentences up to token limit
            sentence_scores.sort(key=lambda x: x[1], reverse=True)
            
            compressed_text = ""
            for sentence, _ in sentence_scores:
                # Rough token estimate
                if len(compressed_text.split()) + len(sentence.split()) <= self.config.max_tokens_per_doc:
                    compressed_text += sentence + ". "
                else:
                    break
            
            # Create compressed document
            compressed_doc = doc.copy()
            compressed_doc["document"] = compressed_text.strip()
            compressed_doc["original_length"] = len(doc["document"])
            compressed_docs.append(compressed_doc)
        
        result.documents = compressed_docs
        result.metadata["compressed"] = True
        
        return result
    
    def _expand_query(self, query: str) -> List[str]:
        """Expand query with synonyms and related terms."""
        # Simple expansion - in production, use WordNet, embeddings, or LLM
        expanded = [query]
        
        # Add query without stop words
        stop_words = {"the", "a", "an", "is", "are", "was", "were", "what", "how", "why"}
        filtered_query = " ".join([
            word for word in query.split()
            if word.lower() not in stop_words
        ])
        
        if filtered_query != query:
            expanded.append(filtered_query)
        
        return expanded
    
    def _choose_strategy(
        self,
        query: str,
        decomposition_result: Optional[Any]
    ) -> RetrievalStrategy:
        """Adaptively choose retrieval strategy based on query."""
        # Simple heuristics - in production, use learned model
        
        # Multi-hop for complex decomposed queries
        if decomposition_result and len(getattr(decomposition_result, 'sub_queries', [])) > 2:
            return RetrievalStrategy.MULTI_HOP
        
        # Sparse for keyword-heavy queries
        if len(query.split()) <= 3:
            return RetrievalStrategy.SPARSE
        
        # Default to hybrid
        return RetrievalStrategy.HYBRID
    
    def _get_all_documents(self, filter_metadata: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Retrieve all documents from the vector store for BM25 corpus construction."""
        try:
            all_docs = self.vector_store.get_all_documents()
        except Exception:
            return []
        if not filter_metadata:
            return all_docs
        return [
            doc for doc in all_docs
            if all(
                doc.get("metadata", {}).get(k) == v
                for k, v in filter_metadata.items()
            )
        ]
