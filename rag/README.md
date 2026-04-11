# VersaAI RAG System

Production-grade Retrieval-Augmented Generation (RAG) system for VersaAI.

## 🎯 Overview

The VersaAI RAG system is a comprehensive, modular RAG implementation designed for production use. It provides intelligent document retrieval, answer generation, and quality assurance through a multi-stage pipeline.

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      RAG Pipeline                            │
├─────────────────────────────────────────────────────────────┤
│  1. Query Decomposition  →  Break complex queries           │
│  2. Planning             →  Create execution plan           │
│  3. Adaptive Retrieval   →  Multi-strategy document fetch   │
│  4. Reranking            →  Optimize result ordering        │
│  5. Synthesis            →  Generate answer from context    │
│  6. Critique             →  Quality assessment              │
│  7. Refinement           →  Iterative improvement           │
└─────────────────────────────────────────────────────────────┘
```

## 📦 Components

### 1. **Query Decomposer** (`query_decomposer.py`)
Breaks down complex queries into manageable sub-queries.

**Features:**
- Multi-hop query decomposition
- Temporal awareness (date/time queries)
- Entity extraction
- Dependency tracking
- LLM and heuristic modes

**Example:**
```python
from versaai.rag import QueryDecomposer

decomposer = QueryDecomposer(use_llm=False)
result = decomposer.decompose("What is machine learning and how does it differ from AI?")

print(f"Query type: {result.query_type}")
print(f"Sub-queries: {len(result.sub_queries)}")
print(f"Complexity: {result.complexity_score}")
```

### 2. **Planner Agent** (`planner.py`)
Creates optimal execution plans for query processing.

**Features:**
- Multi-step plan generation
- Dependency management
- Parallel execution optimization
- Adaptive re-planning
- Resource-aware scheduling

**Example:**
```python
from versaai.rag import PlannerAgent

planner = PlannerAgent(use_llm=False)
plan = planner.create_plan("Explain neural networks")

print(planner.visualize_plan(plan))
```

### 3. **Critic Agent** (`critic.py`)
Evaluates answer quality across multiple dimensions.

**Features:**
- Factual accuracy checking
- Relevance evaluation
- Completeness assessment
- Hallucination detection
- Citation quality validation
- Coherence analysis

**Dimensions:**
- `FACTUALITY` - Are facts correct?
- `RELEVANCE` - Does answer address query?
- `COMPLETENESS` - Is answer complete?
- `COHERENCE` - Is answer well-structured?
- `CITATION` - Are sources cited properly?
- `HALLUCINATION` - Any fabricated content?
- `CONSISTENCY` - Internal consistency check

**Example:**
```python
from versaai.rag import CriticAgent, CriticConfig, CriticDimension

config = CriticConfig(
    enabled_dimensions=[CriticDimension.FACTUALITY, CriticDimension.RELEVANCE]
)
critic = CriticAgent(config)

critique = critic.critique(query, answer, retrieved_docs)
print(f"Overall score: {critique.overall_score}")
print(f"Issues: {len(critique.issues)}")
```

### 4. **Adaptive Retriever** (`retriever.py`)
Multi-strategy document retrieval system.

**Strategies:**
- **Dense**: Vector similarity search
- **Sparse**: BM25 keyword search  
- **Hybrid**: Combined dense + sparse (RRF fusion)
- **Multi-hop**: For complex queries
- **Adaptive**: Auto-select best strategy

**Features:**
- Cross-encoder reranking
- MMR for diversity
- Query expansion
- Contextual compression

**Example:**
```python
from versaai.rag import AdaptiveRetriever, RetrieverConfig, RetrievalStrategy

config = RetrieverConfig(
    strategy=RetrievalStrategy.HYBRID,
    top_k=10,
    rerank_top_k=5
)

retriever = AdaptiveRetriever(vector_store, embedding_model, config)
result = retriever.retrieve("What is Python?")

print(f"Retrieved {len(result.documents)} documents")
print(f"Strategy used: {result.strategy_used}")
```

### 5. **Vector Store** (`vector_store.py`)
Unified vector storage interface.

**Backends:**
- ChromaDB (persistent, remote)
- FAISS (high-performance)
- In-memory (testing)

**Example:**
```python
from versaai.rag import VectorStore, VectorStoreConfig, VectorStoreType
from pathlib import Path

config = VectorStoreConfig(
    store_type=VectorStoreType.CHROMADB,
    persist_directory=Path("./chroma_db"),
    collection_name="my_documents"
)

store = VectorStore(config, embedding_model)
store.add_documents(documents, metadata=metadata)
results = store.search("query", k=5)
```

### 6. **Embedding Model** (`embeddings.py`)
Efficient text embedding generation.

**Features:**
- Sentence Transformers support
- GPU acceleration
- Batch processing
- Normalization
- Caching

**Example:**
```python
from versaai.rag import EmbeddingModel, EmbeddingConfig

config = EmbeddingConfig(
    model_name="sentence-transformers/all-MiniLM-L6-v2",
    device="cuda",  # or "cpu"
    batch_size=32
)

model = EmbeddingModel(config)
embeddings = model.embed_texts(["text1", "text2", "text3"])
```

### 7. **RAG Pipeline** (`pipeline.py`)
Complete end-to-end RAG workflow.

**Features:**
- Modular architecture
- Configurable stages
- Quality assurance
- Performance monitoring
- Result caching
- Iterative refinement

**Example:**
```python
from versaai.rag import RAGPipeline, RAGConfig

config = RAGConfig(
    enable_decomposition=True,
    enable_planning=True,
    enable_critique=True,
    enable_refinement=True,
    min_acceptable_score=0.7
)

pipeline = RAGPipeline(config, llm_model=my_llm)

# Add documents
pipeline.add_documents(documents)

# Query
result = pipeline.query("What is machine learning?")

print(result.answer)
print(f"Confidence: {result.confidence_score}")
print(f"Sources: {result.sources}")
```

## 🚀 Quick Start

### Installation

```bash
# Install dependencies
pip install sentence-transformers chromadb faiss-cpu rank-bm25 numpy

# Optional: For GPU support
pip install faiss-gpu
```

### Basic Usage

```python
from versaai.rag import RAGPipeline, RAGConfig

# Initialize pipeline
pipeline = RAGPipeline(RAGConfig())

# Add knowledge base
documents = [
    "Python is a high-level programming language.",
    "Machine learning is a subset of artificial intelligence.",
    "Deep learning uses neural networks."
]
pipeline.add_documents(documents)

# Query the system
result = pipeline.query("What is Python?")
print(result.answer)
```

## 📊 Performance Benchmarks

Tested on Intel i7-10700K, 32GB RAM:

| Operation | Throughput | Latency |
|-----------|-----------|---------|
| Embedding (batch=32) | ~150 texts/sec | ~200ms |
| Dense Retrieval (10k docs) | ~100 queries/sec | ~10ms |
| Hybrid Retrieval | ~50 queries/sec | ~20ms |
| End-to-end Pipeline | ~2 queries/sec | ~500ms |

## 🧪 Testing

Run the comprehensive test suite:

```bash
# All tests
python tests/rag/test_rag_system.py

# Specific test class
python -m unittest tests.rag.test_rag_system.TestRAGPipeline

# With verbose output
python tests/rag/test_rag_system.py -v
```

**Test Coverage:**
- Unit tests for all components
- Integration tests for pipeline
- Performance benchmarks
- Quality metrics validation

## 🎨 Configuration

### Pipeline Configuration

```python
config = RAGConfig(
    # Component configs
    embedding_config=EmbeddingConfig(...),
    vector_store_config=VectorStoreConfig(...),
    retriever_config=RetrieverConfig(...),
    critic_config=CriticConfig(...),
    
    # Pipeline behavior
    enable_decomposition=True,
    enable_planning=True,
    enable_critique=True,
    enable_refinement=True,
    
    # Quality thresholds
    min_acceptable_score=0.7,
    max_refinement_iterations=3,
    
    # Performance
    cache_results=True,
    parallel_retrieval=True
)
```

### Retriever Configuration

```python
config = RetrieverConfig(
    strategy=RetrievalStrategy.HYBRID,
    top_k=10,
    rerank_top_k=5,
    rerank_method=RerankMethod.CROSS_ENCODER,
    
    # Weights for hybrid
    dense_weight=0.7,
    sparse_weight=0.3,
    
    # Diversity
    use_mmr=True,
    mmr_lambda=0.5,
    
    # Compression
    use_compression=True,
    max_tokens_per_doc=500
)
```

### Critic Configuration

```python
config = CriticConfig(
    use_llm=False,
    enabled_dimensions=[
        CriticDimension.FACTUALITY,
        CriticDimension.RELEVANCE,
        CriticDimension.COMPLETENESS,
        CriticDimension.HALLUCINATION
    ],
    min_acceptable_score=0.7,
    check_citations=True,
    strict_mode=False
)
```

## 📈 Monitoring & Metrics

Get pipeline statistics:

```python
stats = pipeline.get_stats()
print(f"Total queries: {stats['total_queries']}")
print(f"Success rate: {stats['successful_queries'] / stats['total_queries']}")
print(f"Average score: {stats['average_score']}")
print(f"Average time: {stats['average_time']}")
```

## 🔧 Advanced Usage

### Custom Callbacks

```python
from versaai.rag import PipelineStage

def on_retrieval(result):
    print(f"Retrieved {len(result.documents)} documents")

def on_critique(critique):
    if not critique.is_acceptable():
        print(f"Quality issues: {len(critique.issues)}")

callbacks = {
    PipelineStage.RETRIEVAL: on_retrieval,
    PipelineStage.CRITIQUE: on_critique
}

result = pipeline.query("query", callbacks=callbacks)
```

### Multi-hop Queries

```python
# The system automatically handles complex queries
result = pipeline.query(
    "Who is the CEO of the company that created ChatGPT, "
    "and what other companies has that person founded?"
)
```

### Quality-Driven Refinement

```python
config = RAGConfig(
    enable_refinement=True,
    min_acceptable_score=0.8,  # Higher threshold
    max_refinement_iterations=5
)

pipeline = RAGPipeline(config, llm_model=llm)
result = pipeline.query("complex query")

# Result will be refined until it meets quality threshold
```

## 🎓 Best Practices

1. **Document Chunking**: Chunk documents to 200-500 tokens for optimal retrieval
2. **Metadata**: Include rich metadata (source, date, category) for filtering
3. **Batch Operations**: Use batch document addition for large datasets
4. **Caching**: Enable caching for repeated queries
5. **Quality Thresholds**: Set appropriate quality thresholds for your use case
6. **Monitoring**: Regularly check statistics and critique scores

## 🔍 Troubleshooting

### Low Retrieval Quality
- Increase `top_k` parameter
- Try `RetrievalStrategy.HYBRID`
- Enable query expansion
- Check document chunking

### Slow Performance
- Reduce `top_k`
- Disable unnecessary pipeline stages
- Use GPU for embeddings
- Enable result caching

### Poor Answer Quality
- Enable critique and refinement
- Increase `min_acceptable_score`
- Add more relevant documents
- Use reranking

## 📝 License

Part of VersaAI - See main project LICENSE

## 🤝 Contributing

Follow VersaAI contribution guidelines in main project CONTRIBUTING.md

## 📧 Support

For issues specific to the RAG system, please file an issue in the main VersaAI repository.
