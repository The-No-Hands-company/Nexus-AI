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
    "EmbeddingModel": "src.rag.embeddings",
    "EmbeddingConfig": "src.rag.embeddings",
    # Chunker
    "DocumentChunker": "src.rag.chunker",
    "ChunkerConfig": "src.rag.chunker",
    "Chunk": "src.rag.chunker",
    # Vector Store
    "VectorStore": "src.rag.vector_store",
    "VectorStoreConfig": "src.rag.vector_store",
    "VectorStoreType": "src.rag.vector_store",
    # RAG System (unified facade)
    "RAGSystem": "src.rag.rag_system",
    # Query Decomposer
    "QueryDecomposer": "src.rag.query_decomposer",
    "DecompositionResult": "src.rag.query_decomposer",
    "SubQuery": "src.rag.query_decomposer",
    "QueryType": "src.rag.query_decomposer",
    # Planner
    "PlannerAgent": "src.rag.planner",
    "Plan": "src.rag.planner",
    "PlanStep": "src.rag.planner",
    "StepType": "src.rag.planner",
    "StepStatus": "src.rag.planner",
    # Critic
    "CriticAgent": "src.rag.critic",
    "Critique": "src.rag.critic",
    "CriticConfig": "src.rag.critic",
    "CriticDimension": "src.rag.critic",
    "CriticSeverity": "src.rag.critic",
    "CriticIssue": "src.rag.critic",
    "DimensionScore": "src.rag.critic",
    # Retriever
    "AdaptiveRetriever": "src.rag.retriever",
    "RetrieverConfig": "src.rag.retriever",
    "RetrievalStrategy": "src.rag.retriever",
    "RerankMethod": "src.rag.retriever",
    "RetrievalResult": "src.rag.retriever",
    # Pipeline
    "RAGPipeline": "src.rag.pipeline",
    "RAGConfig": "src.rag.pipeline",
    "RAGResult": "src.rag.pipeline",
    "PipelineStage": "src.rag.pipeline",
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
