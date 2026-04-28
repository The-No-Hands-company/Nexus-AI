"""
Production-grade Planner Agent for RAG system.

The Planner Agent creates optimal execution plans for complex queries:
- Breaks down queries into actionable steps
- Optimizes execution order
- Resource allocation
- Parallel execution planning
- Adaptive re-planning based on intermediate results
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)
from .logging_compat import HAS_CPP_LOGGER


class StepType(Enum):
    """Types of execution steps in a plan."""
    RETRIEVE = "retrieve"  # Retrieve information from vector store
    DECOMPOSE = "decompose"  # Decompose query
    SYNTHESIZE = "synthesize"  # Synthesize information
    VALIDATE = "validate"  # Validate results
    RERANK = "rerank"  # Rerank retrieved documents
    FILTER = "filter"  # Filter results based on criteria
    EXECUTE_TOOL = "execute_tool"  # Execute external tool


class StepStatus(Enum):
    """Status of a plan step."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PlanStep:
    """A single step in an execution plan."""
    
    step_id: int
    step_type: StepType
    description: str
    dependencies: List[int] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    status: StepStatus = StepStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_time: float = 0.0
    retry_count: int = 0
    max_retries: int = 3
    
    def can_execute(self, completed_steps: set) -> bool:
        """Check if step can be executed based on dependencies."""
        return all(dep_id in completed_steps for dep_id in self.dependencies)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "step_id": self.step_id,
            "step_type": self.step_type.value,
            "description": self.description,
            "dependencies": self.dependencies,
            "parameters": self.parameters,
            "status": self.status.value,
            "execution_time": self.execution_time,
            "retry_count": self.retry_count
        }


@dataclass
class Plan:
    """Complete execution plan for a query."""
    
    plan_id: str
    query: str
    steps: List[PlanStep]
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    total_steps: int = 0
    completed_steps: int = 0
    
    def __post_init__(self):
        self.total_steps = len(self.steps)
    
    def get_next_executable_steps(self) -> List[PlanStep]:
        """Get all steps that can be executed in parallel."""
        completed = {
            step.step_id for step in self.steps 
            if step.status == StepStatus.COMPLETED
        }
        
        return [
            step for step in self.steps
            if step.status == StepStatus.PENDING and step.can_execute(completed)
        ]
    
    def update_step_status(
        self,
        step_id: int,
        status: StepStatus,
        result: Optional[Any] = None,
        error: Optional[str] = None,
        execution_time: float = 0.0
    ):
        """Update status of a step."""
        for step in self.steps:
            if step.step_id == step_id:
                step.status = status
                step.result = result
                step.error = error
                step.execution_time = execution_time
                
                if status == StepStatus.COMPLETED:
                    self.completed_steps += 1
                
                self.updated_at = datetime.now().isoformat()
                break
    
    def is_complete(self) -> bool:
        """Check if all steps are completed."""
        return all(
            step.status in [StepStatus.COMPLETED, StepStatus.SKIPPED]
            for step in self.steps
        )
    
    def has_failed(self) -> bool:
        """Check if any critical step has failed."""
        return any(
            step.status == StepStatus.FAILED and step.retry_count >= step.max_retries
            for step in self.steps
        )
    
    def get_progress(self) -> float:
        """Get execution progress (0.0 to 1.0)."""
        if self.total_steps == 0:
            return 1.0
        return self.completed_steps / self.total_steps
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert plan to dictionary."""
        return {
            "plan_id": self.plan_id,
            "query": self.query,
            "steps": [step.to_dict() for step in self.steps],
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "progress": self.get_progress()
        }


class PlannerAgent:
    """
    Production-grade Planner Agent for optimal query execution.
    
    Capabilities:
    - Query analysis and complexity assessment
    - Multi-step plan generation
    - Dependency management
    - Parallel execution optimization
    - Adaptive re-planning
    - Resource-aware scheduling
    """
    
    def __init__(
        self,
        use_llm: bool = False,
        llm_model: Optional[Any] = None,
        max_plan_steps: int = 20,
        enable_parallel_execution: bool = True
    ):
        """
        Initialize Planner Agent.
        
        Args:
            use_llm: Use LLM for intelligent planning
            llm_model: Optional LLM model for plan generation
            max_plan_steps: Maximum number of steps in a plan
            enable_parallel_execution: Enable parallel step execution
        """
        self.use_llm = use_llm
        self.llm_model = llm_model
        self.max_plan_steps = max_plan_steps
        self.enable_parallel_execution = enable_parallel_execution
        
        self._plan_counter = 0
        self._plan_cache: Dict[str, Plan] = {}
        
        if HAS_CPP_LOGGER:
            logger.info(
                f"PlannerAgent initialized (LLM: {use_llm}, parallel: {enable_parallel_execution})",
                "PlannerAgent"
            )
        else:
            logger.info(
                f"PlannerAgent initialized (LLM: {use_llm}, parallel: {enable_parallel_execution})"
            )
    
    def create_plan(
        self,
        query: str,
        decomposition_result: Optional[Any] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Plan:
        """
        Create an optimal execution plan for a query.
        
        Args:
            query: User query
            decomposition_result: Optional query decomposition
            context: Optional additional context
            
        Returns:
            Complete execution plan
        """
        if HAS_CPP_LOGGER:
            logger.info(f"Creating plan for query: {query[:100]}...", "PlannerAgent")
        else:
            logger.info(f"Creating plan for query: {query[:100]}...")
        
        self._plan_counter += 1
        plan_id = f"plan_{self._plan_counter}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Generate plan steps
        if self.use_llm and self.llm_model:
            steps = self._create_plan_with_llm(query, decomposition_result, context)
        else:
            steps = self._create_plan_heuristic(query, decomposition_result, context)
        
        # Create plan
        plan = Plan(
            plan_id=plan_id,
            query=query,
            steps=steps,
            metadata={
                "planning_method": "llm" if self.use_llm else "heuristic",
                "has_decomposition": decomposition_result is not None,
                "parallel_enabled": self.enable_parallel_execution
            }
        )
        
        # Cache plan
        self._plan_cache[plan_id] = plan
        
        if HAS_CPP_LOGGER:
            logger.info(
                f"Plan created: {plan_id} with {len(steps)} steps",
                "PlannerAgent"
            )
        else:
            logger.info(f"Plan created: {plan_id} with {len(steps)} steps")
        
        return plan
    
    def _create_plan_heuristic(
        self,
        query: str,
        decomposition_result: Optional[Any],
        context: Optional[Dict[str, Any]]
    ) -> List[PlanStep]:
        """Create plan using heuristic rules."""
        steps = []
        step_id = 0
        
        # Step 1: Query decomposition (if not already done)
        if decomposition_result is None:
            steps.append(PlanStep(
                step_id=step_id,
                step_type=StepType.DECOMPOSE,
                description="Decompose query into sub-queries",
                dependencies=[],
                parameters={"query": query}
            ))
            step_id += 1
            decompose_step_id = step_id - 1
        else:
            decompose_step_id = -1
        
        # Step 2: Retrieve relevant documents
        steps.append(PlanStep(
            step_id=step_id,
            step_type=StepType.RETRIEVE,
            description="Retrieve relevant documents from vector store",
            dependencies=[decompose_step_id] if decompose_step_id >= 0 else [],
            parameters={
                "query": query,
                "top_k": 10,
                "use_decomposition": decomposition_result is not None
            }
        ))
        retrieve_step_id = step_id
        step_id += 1
        
        # Step 3: Rerank retrieved documents
        steps.append(PlanStep(
            step_id=step_id,
            step_type=StepType.RERANK,
            description="Rerank documents by relevance",
            dependencies=[retrieve_step_id],
            parameters={
                "method": "cross-encoder",
                "top_k": 5
            }
        ))
        rerank_step_id = step_id
        step_id += 1
        
        # Step 4: Filter irrelevant results
        steps.append(PlanStep(
            step_id=step_id,
            step_type=StepType.FILTER,
            description="Filter out low-confidence results",
            dependencies=[rerank_step_id],
            parameters={
                "min_score": 0.5,
                "diversity_threshold": 0.7
            }
        ))
        filter_step_id = step_id
        step_id += 1
        
        # Step 5: Synthesize final answer
        steps.append(PlanStep(
            step_id=step_id,
            step_type=StepType.SYNTHESIZE,
            description="Synthesize answer from filtered documents",
            dependencies=[filter_step_id],
            parameters={
                "query": query,
                "max_context_length": 4000
            }
        ))
        synthesize_step_id = step_id
        step_id += 1
        
        # Step 6: Validate answer
        steps.append(PlanStep(
            step_id=step_id,
            step_type=StepType.VALIDATE,
            description="Validate generated answer",
            dependencies=[synthesize_step_id],
            parameters={
                "check_factuality": True,
                "check_completeness": True
            }
        ))
        step_id += 1
        
        return steps
    
    def _create_plan_with_llm(
        self,
        query: str,
        decomposition_result: Optional[Any],
        context: Optional[Dict[str, Any]]
    ) -> List[PlanStep]:
        """Create plan using LLM for intelligent planning."""
        prompt = self._build_planning_prompt(query, decomposition_result, context)
        
        try:
            response = self.llm_model.generate(
                prompt,
                max_tokens=1000,
                temperature=0.2  # Low temperature for structured output
            )
            
            steps = self._parse_llm_plan(response)
            return steps
            
        except Exception as e:
            if HAS_CPP_LOGGER:
                logger.error(
                    f"LLM planning failed, using heuristic: {e}",
                    "PlannerAgent"
                )
            else:
                logger.error(f"LLM planning failed, using heuristic: {e}")
            
            return self._create_plan_heuristic(query, decomposition_result, context)
    
    def _build_planning_prompt(
        self,
        query: str,
        decomposition_result: Optional[Any],
        context: Optional[Dict[str, Any]]
    ) -> str:
        """Build prompt for LLM-based planning."""
        prompt = f"""Create an optimal execution plan for answering this query.

Query: {query}

Available step types:
- RETRIEVE: Retrieve information from vector store
- DECOMPOSE: Decompose complex query
- SYNTHESIZE: Synthesize information into answer
- VALIDATE: Validate results
- RERANK: Rerank retrieved documents
- FILTER: Filter results
- EXECUTE_TOOL: Execute external tool

For each step, provide:
1. Step type
2. Description
3. Dependencies (step IDs it depends on)
4. Parameters (key-value pairs)

Format:
Step 1: RETRIEVE | Description | Dependencies: [] | Parameters: {{"top_k": 10}}
Step 2: RERANK | Description | Dependencies: [1] | Parameters: {{"method": "cross-encoder"}}

Create an optimal plan (max {self.max_plan_steps} steps):
"""
        
        if decomposition_result:
            prompt += f"\nQuery has been decomposed into sub-queries. Plan accordingly.\n"
        
        if context:
            prompt += f"\nAdditional context: {json.dumps(context, indent=2)}\n"
        
        prompt += "\nExecution Plan:\n"
        return prompt
    
    def _parse_llm_plan(self, response: str) -> List[PlanStep]:
        """Parse LLM response into PlanStep objects."""
        steps = []
        lines = response.strip().split('\n')
        
        for line in lines:
            if not line.strip() or not line.startswith("Step"):
                continue
            
            try:
                # Parse: "Step N: TYPE | Description | Dependencies: [...] | Parameters: {...}"
                parts = line.split('|')
                
                # Extract step ID and type
                step_header = parts[0].split(':')
                step_id = int(step_header[0].replace("Step", "").strip()) - 1
                step_type_str = step_header[1].strip()
                step_type = StepType[step_type_str.upper()]
                
                # Extract description
                description = parts[1].strip()
                
                # Extract dependencies
                deps_str = parts[2].split(':', 1)[1].strip()
                dependencies = []
                if deps_str != '[]':
                    dependencies = [
                        int(x.strip()) - 1  # Convert to 0-indexed
                        for x in deps_str[1:-1].split(',') if x.strip()
                    ]
                
                # Extract parameters
                params_str = parts[3].split(':', 1)[1].strip()
                parameters = json.loads(params_str) if params_str else {}
                
                steps.append(PlanStep(
                    step_id=step_id,
                    step_type=step_type,
                    description=description,
                    dependencies=dependencies,
                    parameters=parameters
                ))
                
            except Exception as e:
                if HAS_CPP_LOGGER:
                    logger.warning(f"Failed to parse plan step: {line} - {e}", "PlannerAgent")
                else:
                    logger.warning(f"Failed to parse plan step: {line} - {e}")
                continue
        
        return steps if steps else self._create_fallback_plan()
    
    def _create_fallback_plan(self) -> List[PlanStep]:
        """Create minimal fallback plan."""
        return [
            PlanStep(
                step_id=0,
                step_type=StepType.RETRIEVE,
                description="Retrieve relevant documents",
                dependencies=[],
                parameters={"top_k": 5}
            ),
            PlanStep(
                step_id=1,
                step_type=StepType.SYNTHESIZE,
                description="Generate answer",
                dependencies=[0],
                parameters={}
            )
        ]
    
    def replan(
        self,
        plan: Plan,
        failed_step: PlanStep,
        intermediate_results: Dict[int, Any]
    ) -> Plan:
        """
        Adaptive re-planning when a step fails.
        
        Args:
            plan: Current plan
            failed_step: Step that failed
            intermediate_results: Results from completed steps
            
        Returns:
            Updated plan with alternative strategy
        """
        if HAS_CPP_LOGGER:
            logger.info(
                f"Re-planning after step {failed_step.step_id} failure",
                "PlannerAgent"
            )
        else:
            logger.info(f"Re-planning after step {failed_step.step_id} failure")
        
        # Create alternative steps for failed step
        alternative_steps = self._generate_alternative_steps(
            failed_step,
            intermediate_results
        )
        
        # Update plan with alternatives
        new_steps = []
        for step in plan.steps:
            if step.step_id == failed_step.step_id:
                # Replace with alternatives
                new_steps.extend(alternative_steps)
            else:
                # Keep original step, update dependencies if needed
                if failed_step.step_id in step.dependencies:
                    # Update dependency to point to last alternative step
                    step.dependencies.remove(failed_step.step_id)
                    if alternative_steps:
                        step.dependencies.append(alternative_steps[-1].step_id)
                new_steps.append(step)
        
        # Create new plan
        new_plan = Plan(
            plan_id=f"{plan.plan_id}_replan_{len([s for s in plan.steps if s.status == StepStatus.FAILED])}",
            query=plan.query,
            steps=new_steps,
            metadata={
                **plan.metadata,
                "replanned": True,
                "failed_step": failed_step.step_id
            }
        )
        
        return new_plan
    
    def _generate_alternative_steps(
        self,
        failed_step: PlanStep,
        intermediate_results: Dict[int, Any]
    ) -> List[PlanStep]:
        """Generate alternative steps for a failed step."""
        alternatives = []
        
        if failed_step.step_type == StepType.RETRIEVE:
            # Try different retrieval strategy
            alternatives.append(PlanStep(
                step_id=failed_step.step_id,
                step_type=StepType.RETRIEVE,
                description="Retrieve with relaxed constraints",
                dependencies=failed_step.dependencies,
                parameters={
                    **failed_step.parameters,
                    "top_k": failed_step.parameters.get("top_k", 10) * 2,
                    "min_score": 0.3  # Lower threshold
                }
            ))
        
        elif failed_step.step_type == StepType.SYNTHESIZE:
            # Try simpler synthesis
            alternatives.append(PlanStep(
                step_id=failed_step.step_id,
                step_type=StepType.SYNTHESIZE,
                description="Synthesize with simpler method",
                dependencies=failed_step.dependencies,
                parameters={
                    **failed_step.parameters,
                    "method": "extractive"  # Simpler than abstractive
                }
            ))
        
        else:
            # Generic retry with adjusted parameters
            alternatives.append(PlanStep(
                step_id=failed_step.step_id,
                step_type=failed_step.step_type,
                description=f"Retry: {failed_step.description}",
                dependencies=failed_step.dependencies,
                parameters=failed_step.parameters
            ))
        
        return alternatives
    
    def visualize_plan(self, plan: Plan) -> str:
        """
        Create human-readable visualization of plan.
        
        Args:
            plan: Plan to visualize
            
        Returns:
            Formatted string representation
        """
        lines = [
            f"Plan ID: {plan.plan_id}",
            f"Query: {plan.query}",
            f"Progress: {plan.get_progress() * 100:.1f}% ({plan.completed_steps}/{plan.total_steps})",
            f"Status: {'Complete' if plan.is_complete() else 'In Progress'}",
            "",
            "Execution Steps:"
        ]
        
        for step in plan.steps:
            status_symbol = {
                StepStatus.PENDING: "⏳",
                StepStatus.IN_PROGRESS: "🔄",
                StepStatus.COMPLETED: "✅",
                StepStatus.FAILED: "❌",
                StepStatus.SKIPPED: "⏭️"
            }.get(step.status, "❓")
            
            deps = f" (deps: {step.dependencies})" if step.dependencies else ""
            time = f" [{step.execution_time:.2f}s]" if step.execution_time > 0 else ""
            
            lines.append(
                f"  {status_symbol} Step {step.step_id + 1}: "
                f"{step.step_type.value} - {step.description}{deps}{time}"
            )
            
            if step.error:
                lines.append(f"      Error: {step.error}")
        
        return "\n".join(lines)
    
    def get_plan(self, plan_id: str) -> Optional[Plan]:
        """Retrieve cached plan by ID."""
        return self._plan_cache.get(plan_id)
    
    def clear_cache(self):
        """Clear plan cache."""
        self._plan_cache.clear()
        if HAS_CPP_LOGGER:
            logger.info("Plan cache cleared", "PlannerAgent")
        else:
            logger.info("Plan cache cleared")
