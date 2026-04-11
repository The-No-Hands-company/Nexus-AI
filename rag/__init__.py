"""
VersaAI RAG (Retrieval-Augmented Generation) Infrastructure.

Production-grade RAG components:
- Embeddings (Ollama, sentence-transformers, hash fallback)
- Document chunking (recursive character splitting, code-aware)
- Vector stores (ChromaDB, FAISS, in-memory)
- Query decomposition & retrieval strategies
- Planner & Critic agents
- Complete RAG pipeline & unified RAGSystem facade
"""

import importlib as _importlib

# Lazy imports — avoids pulling in numpy/chromadb/faiss/sentence-transformers
# at module load time. Each name resolves on first access.
_LAZY_MAP: dict[str, str] = {
    # Embeddings
    "EmbeddingModel": "versaai.rag.embeddings",
    "EmbeddingConfig": "versaai.rag.embeddings",
    # Chunker
    "DocumentChunker": "versaai.rag.chunker",
    "ChunkerConfig": "versaai.rag.chunker",
    "Chunk": "versaai.rag.chunker",
    # Vector Store
    "VectorStore": "versaai.rag.vector_store",
    "VectorStoreConfig": "versaai.rag.vector_store",
    "VectorStoreType": "versaai.rag.vector_store",
    # RAG System (unified facade)
    "RAGSystem": "versaai.rag.rag_system",
    # Query Decomposer
    "QueryDecomposer": "versaai.rag.query_decomposer",
    "DecompositionResult": "versaai.rag.query_decomposer",
    "SubQuery": "versaai.rag.query_decomposer",
    "QueryType": "versaai.rag.query_decomposer",
    # Planner
    "PlannerAgent": "versaai.rag.planner",
    "Plan": "versaai.rag.planner",
    "PlanStep": "versaai.rag.planner",
    "StepType": "versaai.rag.planner",
    "StepStatus": "versaai.rag.planner",
    # Critic
    "CriticAgent": "versaai.rag.critic",
    "Critique": "versaai.rag.critic",
    "CriticConfig": "versaai.rag.critic",
    "CriticDimension": "versaai.rag.critic",
    "CriticSeverity": "versaai.rag.critic",
    "CriticIssue": "versaai.rag.critic",
    "DimensionScore": "versaai.rag.critic",
    # Retriever
    "AdaptiveRetriever": "versaai.rag.retriever",
    "RetrieverConfig": "versaai.rag.retriever",
    "RetrievalStrategy": "versaai.rag.retriever",
    "RerankMethod": "versaai.rag.retriever",
    "RetrievalResult": "versaai.rag.retriever",
    # Pipeline
    "RAGPipeline": "versaai.rag.pipeline",
    "RAGConfig": "versaai.rag.pipeline",
    "RAGResult": "versaai.rag.pipeline",
    "PipelineStage": "versaai.rag.pipeline",
}


def __getattr__(name: str):
    if name in _LAZY_MAP:
        module = _importlib.import_module(_LAZY_MAP[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Embeddings
    "EmbeddingModel",
    "EmbeddingConfig",

    # Chunker
    "DocumentChunker",
    "ChunkerConfig",
    "Chunk",

    # Vector Store
    "VectorStore",
    "VectorStoreConfig",
    "VectorStoreType",

    # RAG System
    "RAGSystem",

    # Query Decomposer
    "QueryDecomposer",
    "DecompositionResult",
    "SubQuery",
    "QueryType",

    # Planner
    "PlannerAgent",
    "Plan",
    "PlanStep",
    "StepType",
    "StepStatus",

    # Critic
    "CriticAgent",
    "Critique",
    "CriticConfig",
    "CriticDimension",
    "CriticSeverity",
    "CriticIssue",
    "DimensionScore",

    # Retriever
    "AdaptiveRetriever",
    "RetrieverConfig",
    "RetrievalStrategy",
    "RerankMethod",
    "RetrievalResult",

    # Pipeline
    "RAGPipeline",
    "RAGConfig",
    "RAGResult",
    "PipelineStage",
]
