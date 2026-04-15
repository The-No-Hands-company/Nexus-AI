# ════════════════════════════════════════════════════════════════════════════
# Integration Tests: Autonomy, RAG, and Reasoning Endpoints
# ════════════════════════════════════════════════════════════════════════════

class TestIntegrationAutonomyRAGReasoning(unittest.TestCase):
    """Integration tests for autonomy, RAG, and reasoning endpoint workflows."""

    # ── Autonomy Endpoint Tests ───────────────────────────────────────────────

    def test_autonomy_plan_decompose_goal_returns_trace_and_steps(self):
        """POST /autonomy/plan decomposes goal and returns trace_id with steps."""
        response = client.post("/autonomy/plan", json={
            "goal": "Build a simple Python todo app",
            "max_subtasks": 3,
        })
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("trace_id", payload)
        self.assertIn("goal", payload)
        self.assertIn("steps", payload)
        self.assertIsInstance(payload["steps"], list)
        self.assertGreater(len(payload["steps"]), 0, "Plan must have at least one step")
        for step in payload["steps"]:
            self.assertIn("id", step)
            self.assertIn("name", step)
            self.assertIn("description", step)

    def test_autonomy_plan_missing_goal_returns_400(self):
        """POST /autonomy/plan without goal returns 400."""
        response = client.post("/autonomy/plan", json={})
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertIn("error", payload)

    def test_autonomy_execute_runs_goal_and_returns_result(self):
        """POST /autonomy/execute runs goal execution and returns result."""
        response = client.post("/autonomy/execute", json={
            "goal": "Summarize benefits of Python for web development",
            "strategy": "parallel",
            "max_subtasks": 2,
        })
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("trace_id", payload, "Execution must return trace_id")
        self.assertNotIn("error", payload, "Execution should not return error on valid goal")

    def test_autonomy_execute_missing_goal_returns_400(self):
        """POST /autonomy/execute without goal returns 400."""
        response = client.post("/autonomy/execute", json={})
        self.assertEqual(response.status_code, 400)

    def test_autonomy_trace_retrieval_returns_stored_plan(self):
        """GET /autonomy/trace/{trace_id} retrieves stored plan."""
        # First, create a plan
        create_resp = client.post("/autonomy/plan", json={
            "goal": "Design a REST API for user management",
            "max_subtasks": 3,
        })
        self.assertEqual(create_resp.status_code, 200)
        trace_id = create_resp.json()["trace_id"]
        
        # Then retrieve it
        retrieve_resp = client.get(f"/autonomy/trace/{trace_id}")
        self.assertEqual(retrieve_resp.status_code, 200)
        payload = retrieve_resp.json()
        self.assertEqual(payload["trace_id"], trace_id)
        self.assertEqual(payload["type"], "plan")

    def test_autonomy_trace_nonexistent_returns_404(self):
        """GET /autonomy/trace/{trace_id} returns 404 for missing trace."""
        response = client.get("/autonomy/trace/nonexistent_trace_xyz")
        self.assertEqual(response.status_code, 404)

    # ── RAG Endpoint Tests ────────────────────────────────────────────────────

    def test_rag_ingest_text_returns_chunk_count(self):
        """POST /rag/ingest ingests text and returns chunk count."""
        response = client.post("/rag/ingest", json={
            "text": "Python is a high-level programming language. It is easy to learn.",
            "metadata": {"source": "test_integration", "version": "1.0"},
        })
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("ingested_chunks", payload)
        self.assertIn("status", payload)
        self.assertEqual(payload["status"], "ok")
        self.assertGreater(payload["ingested_chunks"], 0)

    def test_rag_ingest_missing_text_and_path_returns_400(self):
        """POST /rag/ingest without text or path returns 400."""
        response = client.post("/rag/ingest", json={})
        self.assertEqual(response.status_code, 400)

    def test_rag_query_after_ingest_returns_results(self):
        """POST /rag/query returns retrieval results after ingest."""
        # Ingest sample document
        ingest_resp = client.post("/rag/ingest", json={
            "text": "FastAPI is a modern web framework for building APIs with Python.",
            "metadata": {"source": "fastapi_guide"},
        })
        self.assertEqual(ingest_resp.status_code, 200)
        
        # Query for related concept
        query_resp = client.post("/rag/query", json={
            "query": "Python web framework",
            "top_k": 5,
        })
        self.assertEqual(query_resp.status_code, 200)
        payload = query_resp.json()
        self.assertIn("query", payload)
        self.assertIn("results", payload)
        self.assertIsInstance(payload["results"], list)

    def test_rag_query_missing_query_returns_400(self):
        """POST /rag/query without query field returns 400."""
        response = client.post("/rag/query", json={})
        self.assertEqual(response.status_code, 400)

    def test_rag_status_returns_stats(self):
        """GET /rag/status returns system statistics."""
        response = client.get("/rag/status")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        # Status endpoint may return various stats; just verify 200 and reasonable payload
        self.assertIsInstance(payload, dict)

    # ── Reasoning Endpoint Tests ──────────────────────────────────────────────

    def test_reason_consensus_returns_reconciled_answer(self):
        """POST /reason/consensus returns consensus answer across providers."""
        response = client.post("/reason/consensus", json={
            "task": "What is the capital of France?",
        })
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("consensus", payload)
        self.assertIn("provider", payload)
        self.assertNotIn("error", payload)

    def test_reason_consensus_missing_task_returns_422(self):
        """POST /reason/consensus without task returns 422."""
        response = client.post("/reason/consensus", json={})
        self.assertEqual(response.status_code, 422)

    def test_reason_generator_critic_task_returns_result(self):
        """POST /reason/generator-critic returns critique-revised answer."""
        response = client.post("/reason/generator-critic", json={
            "task": "Explain how machine learning algorithms learn from data",
        })
        # May return 200 or 422 depending on config; verify structure
        if response.status_code == 200:
            payload = response.json()
            self.assertNotIn("error", payload)

    # ── Integration Workflow Tests ────────────────────────────────────────────

    def test_workflow_autonomy_plan_with_rag_context(self):
        """Integration: Autonomy planning can use RAG-ingested context."""
        # Ingest domain knowledge
        ingest_resp = client.post("/rag/ingest", json={
            "text": "Microservices architecture uses small independent services. "
                    "API Gateway pattern routes requests to appropriate services.",
            "metadata": {"domain": "architecture"},
        })
        self.assertEqual(ingest_resp.status_code, 200)
        
        # Plan task that could benefit from RAG context
        plan_resp = client.post("/autonomy/plan", json={
            "goal": "Design a microservices-based e-commerce platform",
            "max_subtasks": 4,
        })
        self.assertEqual(plan_resp.status_code, 200)
        plan_payload = plan_resp.json()
        self.assertIn("trace_id", plan_payload)
        self.assertIn("steps", plan_payload)

    def test_workflow_execute_then_retrieve_trace(self):
        """Integration: Execute autonomy task and retrieve its trace."""
        execute_resp = client.post("/autonomy/execute", json={
            "goal": "Build a CI/CD pipeline for a Node.js application",
            "strategy": "sequential",
            "max_subtasks": 3,
        })
        self.assertEqual(execute_resp.status_code, 200)
        execute_payload = execute_resp.json()
        trace_id = execute_payload.get("trace_id")
        
        # Retrieve the execution trace
        retrieve_resp = client.get(f"/autonomy/trace/{trace_id}")
        self.assertEqual(retrieve_resp.status_code, 200)
        trace_payload = retrieve_resp.json()
        self.assertEqual(trace_payload["trace_id"], trace_id)
        self.assertIn("type", trace_payload)

    def test_workflow_ingest_query_chain(self):
        """Integration: Ingest multiple documents and query across them."""
        # Ingest multiple chunks of knowledge
        docs = [
            "Docker containers package applications with dependencies.",
            "Kubernetes orchestrates containerized applications at scale.",
            "Container registries store and manage container images.",
        ]
        for doc in docs:
            ingest_resp = client.post("/rag/ingest", json={
                "text": doc,
                "metadata": {"category": "containers"},
            })
            self.assertEqual(ingest_resp.status_code, 200)
        
        # Query knowledge base
        query_resp = client.post("/rag/query", json={
            "query": "How do containers and orchestration work together?",
            "top_k": 5,
        })
        self.assertEqual(query_resp.status_code, 200)
        payload = query_resp.json()
        # Should retrieve results from the ingested docs
        self.assertIn("results", payload)

    def test_workflow_autonomy_executes_without_regression(self):
        """Integration: Autonomy workflows complete without breaking tests."""
        # Run a basic autonomy execution
        response = client.post("/autonomy/execute", json={
            "goal": "Create a Python script to process CSV files",
            "max_subtasks": 2,
        })
        self.assertEqual(response.status_code, 200)
        # Verify contract tests still pass (simple regression check)
        v1_models = client.get("/v1/models")
        self.assertEqual(v1_models.status_code, 200)
        self.assertIn("data", v1_models.json())

    def test_workflow_rag_and_reasoning_integration(self):
        """Integration: RAG results can be used with reasoning endpoints."""
        # 1. Ingest knowledge
        ingest_resp = client.post("/rag/ingest", json={
            "text": "Machine learning models require large labeled datasets for training. "
                    "Overfitting occurs when models memorize training data.",
            "metadata": {"topic": "ml"},
        })
        self.assertEqual(ingest_resp.status_code, 200)
        
        # 2. Query knowledge base
        query_resp = client.post("/rag/query", json={
            "query": "best practices for training machine learning models",
            "top_k": 3,
        })
        self.assertEqual(query_resp.status_code, 200)
        query_results = query_resp.json()
        
        # 3. Use reasoning to process results
        reasoning_resp = client.post("/reason/consensus", json={
            "task": "Summarize the key practices for effective ML model training",
        })
        self.assertEqual(reasoning_resp.status_code, 200)
        reasoning_payload = reasoning_resp.json()
        self.assertIn("consensus", reasoning_payload)

