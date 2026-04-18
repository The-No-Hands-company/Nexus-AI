"""
Smart Model Router for VersaAI Code Models

Automatically selects the best model based on:
- Task complexity
- Programming language
- Required features
- Available system resources
"""

import logging
import re
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

# Import code LLM implementations
try:
    from versaai.models.code_llm import LlamaCppCodeLLM, GenerationConfig
except ImportError:
    LlamaCppCodeLLM = None
    GenerationConfig = None


class TaskComplexity(Enum):
    """Task complexity levels"""
    SIMPLE = "simple"           # Single function, <50 lines
    MEDIUM = "medium"           # Class/module, 50-200 lines
    COMPLEX = "complex"         # Architecture, >200 lines
    REFACTORING = "refactoring" # Code transformation
    DEBUGGING = "debugging"     # Bug fixing


class ModelTier(Enum):
    """Model capability tiers"""
    FAST = "fast"           # Phi-2 (2.7B) - Quick responses
    BALANCED = "balanced"   # DeepSeek/StarCoder2 (6-7B) - Balance speed/quality
    POWERFUL = "powerful"   # CodeLlama/WizardCoder (13-15B) - Best quality


@dataclass
class ModelSpec:
    """Model specification"""
    name: str
    model_id: str
    tier: ModelTier
    size_gb: float
    ram_required_gb: int
    languages: List[str]  # Empty = all languages
    strengths: List[str]
    
    
class ModelRouter:
    """
    Smart router that selects optimal model for each request
    
    Features:
    - Automatic model selection based on task
    - Fallback to smaller models if resources unavailable
    - Language-specific routing
    - Task complexity detection
    """
    
    # Model registry
    MODELS: Dict[str, ModelSpec] = {
        "phi2": ModelSpec(
            name="Phi-2",
            model_id="microsoft/phi-2",
            tier=ModelTier.FAST,
            size_gb=1.5,
            ram_required_gb=4,
            languages=[],  # General purpose
            strengths=["quick", "simple_functions", "code_completion"]
        ),
        
        "deepseek": ModelSpec(
            name="DeepSeek-Coder-6.7B",
            model_id="deepseek-ai/deepseek-coder-6.7b-instruct",
            tier=ModelTier.BALANCED,
            size_gb=4.0,
            ram_required_gb=8,
            languages=["python", "javascript", "java", "c++", "go"],
            strengths=["general_coding", "documentation", "explanations"]
        ),
        
        "starcoder2": ModelSpec(
            name="StarCoder2-7B",
            model_id="bigcode/starcoder2-7b",
            tier=ModelTier.BALANCED,
            size_gb=4.5,
            ram_required_gb=8,
            languages=[],  # 600+ languages
            strengths=["multi_language", "enterprise", "fill_in_middle"]
        ),
        
        "codellama": ModelSpec(
            name="CodeLlama-13B",
            model_id="codellama/CodeLlama-13b-Instruct-hf",
            tier=ModelTier.POWERFUL,
            size_gb=7.5,
            ram_required_gb=16,
            languages=["python", "c++", "java", "php", "typescript"],
            strengths=["algorithms", "complex_logic", "optimization"]
        ),
        
        "wizardcoder": ModelSpec(
            name="WizardCoder-15B",
            model_id="WizardLM/WizardCoder-15B-V1.0",
            tier=ModelTier.POWERFUL,
            size_gb=9.0,
            ram_required_gb=16,
            languages=[],  # Multi-language
            strengths=["debugging", "refactoring", "advanced_features"]
        )
    }
    
    def __init__(self, available_models: Optional[List[str]] = None, 
                 available_ram_gb: int = 16,
                 models_dir: Optional[str] = None):
        """
        Initialize router
        
        Args:
            available_models: List of model IDs that are downloaded
            available_ram_gb: Available system RAM in GB
            models_dir: Directory containing GGUF model files
        """
        self.logger = logging.getLogger(__name__)
        self.available_ram_gb = available_ram_gb
        
        # Model directory
        if models_dir is None:
            models_dir = os.path.expanduser("~/.versaai/models")
        self.models_dir = Path(models_dir)
        
        # Cache for loaded models
        self._loaded_models: Dict[str, LlamaCppCodeLLM] = {}
        
        # If no models specified, assume all are available
        self.available_models = available_models or list(self.MODELS.keys())
        
        # Filter by RAM constraints (only for models in MODELS registry)
        self.usable_models = [
            model_id for model_id in self.available_models
            if model_id in self.MODELS and self.MODELS[model_id].ram_required_gb <= available_ram_gb
        ]
        
        # Add unknown models to usable list (assume they're usable)
        unknown_models = [
            model_id for model_id in self.available_models
            if model_id not in self.MODELS
        ]
        self.usable_models.extend(unknown_models)
        
        if not self.usable_models:
            self.logger.warning(
                f"No models can run with {available_ram_gb}GB RAM. "
                "Minimum required: 4GB"
            )
        
        self.logger.info(
            f"Router initialized with {len(self.usable_models)} usable models: "
            f"{', '.join(self.usable_models)}"
        )
    
    def select_model(
        self, 
        task: str, 
        language: Optional[str] = None,
        prefer_speed: bool = False,
        prefer_quality: bool = False
    ) -> Tuple[str, ModelSpec]:
        """
        Select best model for the task
        
        Args:
            task: Task description
            language: Programming language (auto-detected if None)
            prefer_speed: Prioritize fast response
            prefer_quality: Prioritize output quality
            
        Returns:
            Tuple of (model_id, ModelSpec)
        """
        if not self.usable_models:
            raise RuntimeError("No models available with current RAM constraints")
        
        # Detect language if not provided
        if not language:
            language = self._detect_language(task)
        
        # Detect complexity
        complexity = self._detect_complexity(task)
        
        # Score each model
        scores = {}
        for model_id in self.usable_models:
            score = self._score_model(
                model_id, task, language, complexity,
                prefer_speed, prefer_quality
            )
            scores[model_id] = score
        
        # Select best
        best_model_id = max(scores, key=scores.get)
        best_model = self.MODELS[best_model_id]
        
        self.logger.info(
            f"Selected {best_model.name} for task "
            f"(language={language}, complexity={complexity.value})"
        )
        
        return best_model_id, best_model
    
    def _detect_language(self, task: str) -> Optional[str]:
        """Detect programming language from task description"""
        task_lower = task.lower()
        
        # Language keywords
        language_patterns = {
            "python": ["python", "django", "flask", "pandas", "numpy"],
            "javascript": ["javascript", "js", "react", "node", "vue", "angular"],
            "typescript": ["typescript", "ts", "angular"],
            "java": ["java", "spring", "maven", "gradle"],
            "c++": ["c++", "cpp", "stl"],
            "c": ["c ", "c language"],
            "go": ["golang", "go"],
            "rust": ["rust"],
            "php": ["php", "laravel"],
            "ruby": ["ruby", "rails"],
            "swift": ["swift", "ios"],
            "kotlin": ["kotlin", "android"],
        }
        
        for lang, keywords in language_patterns.items():
            if any(keyword in task_lower for keyword in keywords):
                return lang
        
        return None
    
    def _detect_complexity(self, task: str) -> TaskComplexity:
        """Detect task complexity"""
        task_lower = task.lower()
        
        # Complexity indicators
        if any(word in task_lower for word in [
            "refactor", "restructure", "redesign", "migrate"
        ]):
            return TaskComplexity.REFACTORING
        
        if any(word in task_lower for word in [
            "debug", "fix", "error", "bug", "issue"
        ]):
            return TaskComplexity.DEBUGGING
        
        if any(word in task_lower for word in [
            "architecture", "system", "design pattern", "framework",
            "entire", "complete application", "full"
        ]):
            return TaskComplexity.COMPLEX
        
        if any(word in task_lower for word in [
            "class", "module", "component", "api", "service"
        ]):
            return TaskComplexity.MEDIUM
        
        # Default to simple
        return TaskComplexity.SIMPLE
    
    def _score_model(
        self,
        model_id: str,
        task: str,
        language: Optional[str],
        complexity: TaskComplexity,
        prefer_speed: bool,
        prefer_quality: bool
    ) -> float:
        """
        Score a model for the given task
        
        Returns: Score (0-100, higher is better)
        """
        # Check if model is in registry
        if model_id not in self.MODELS:
            # Unknown model - give it a neutral score
            return 50.0
        
        model = self.MODELS[model_id]
        score = 50.0  # Base score
        
        # 1. Complexity match
        if complexity == TaskComplexity.SIMPLE:
            if model.tier == ModelTier.FAST:
                score += 20
            elif model.tier == ModelTier.BALANCED:
                score += 15
        elif complexity == TaskComplexity.MEDIUM:
            if model.tier == ModelTier.BALANCED:
                score += 20
            elif model.tier == ModelTier.POWERFUL:
                score += 15
        else:  # COMPLEX, REFACTORING, DEBUGGING
            if model.tier == ModelTier.POWERFUL:
                score += 20
            elif model.tier == ModelTier.BALANCED:
                score += 10
        
        # 2. Language match
        if language:
            if not model.languages:  # Multi-language model
                score += 10
            elif language in model.languages:
                score += 15
            else:
                score -= 5  # Penalize if language not in strengths
        
        # 3. Task-specific strengths
        task_lower = task.lower()
        for strength in model.strengths:
            strength_keywords = {
                "quick": ["quick", "simple", "small"],
                "debugging": ["debug", "fix", "error"],
                "refactoring": ["refactor", "improve", "optimize"],
                "algorithms": ["algorithm", "optimize", "performance"],
                "documentation": ["document", "explain", "comment"],
            }
            
            if strength in strength_keywords:
                if any(kw in task_lower for kw in strength_keywords[strength]):
                    score += 10
        
        # 4. User preferences
        if prefer_speed:
            if model.tier == ModelTier.FAST:
                score += 15
            elif model.tier == ModelTier.POWERFUL:
                score -= 10
        
        if prefer_quality:
            if model.tier == ModelTier.POWERFUL:
                score += 15
            elif model.tier == ModelTier.FAST:
                score -= 10
        
        return score
    
    def get_model_info(self, model_id: str) -> Dict:
        """Get detailed model information"""
        if model_id not in self.MODELS:
            raise ValueError(f"Unknown model: {model_id}")
        
        model = self.MODELS[model_id]
        
        return {
            "name": model.name,
            "model_id": model.model_id,
            "tier": model.tier.value,
            "size_gb": model.size_gb,
            "ram_required_gb": model.ram_required_gb,
            "languages": model.languages or ["all"],
            "strengths": model.strengths,
            "available": model_id in self.usable_models
        }
    
    def list_models(self) -> List[Dict]:
        """List all available models with their specs"""
        return [
            self.get_model_info(model_id)
            for model_id in self.MODELS.keys()
        ]
    
    def route(
        self,
        prompt: str,
        task_type: str = "code_completion",
        language: Optional[str] = None,
        prefer_speed: bool = False,
        prefer_quality: bool = False,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[List] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        **kwargs
    ) -> Dict[str, any]:
        """
        Route request to best model and generate response
        
        Args:
            prompt: The input prompt
            task_type: Type of task (code_completion, code_assistant, etc.)
            language: Programming language
            prefer_speed: Prefer fast models
            prefer_quality: Prefer high quality models
            system_prompt: Optional system prompt for the model
            conversation_history: Optional conversation history
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional generation parameters
            
        Returns:
            Dict with 'response', 'model', and 'model_id' keys
        """
        # Select the best model
        model_id, model_spec = self.select_model(
            task=prompt,
            language=language,
            prefer_speed=prefer_speed,
            prefer_quality=prefer_quality
        )
        
        self.logger.info(f"Routing {task_type} to model: {model_spec.name}")
        
        # Try to load and generate with the model
        try:
            response_text = self._generate_with_model(
                model_id=model_id,
                model_spec=model_spec,
                prompt=prompt,
                system_prompt=system_prompt,
                conversation_history=conversation_history,
                max_tokens=max_tokens,
                temperature=temperature
            )
        except Exception as e:
            self.logger.error(f"Model generation failed: {e}")
            # Fallback to placeholder
            response_text = f"Error generating response: {str(e)}"
        
        return {
            'response': response_text,
            'model': model_spec.name,
            'model_id': model_id,
            'task_type': task_type
        }
    
    def _find_model_file(self, model_id: str) -> Optional[Path]:
        """
        Find GGUF model file for the given model_id
        
        Args:
            model_id: Model identifier (e.g., 'deepseek', 'codellama')
            
        Returns:
            Path to model file or None
        """
        if not self.models_dir.exists():
            self.logger.warning(f"Models directory not found: {self.models_dir}")
            return None
        
        # Map model_id to possible filenames
        patterns = {
            'deepseek': ['deepseek-coder-*.gguf', 'deepseek*.gguf'],
            'codellama': ['codellama-*.gguf', 'codellama*.gguf'],
            'starcoder2': ['starcoder2-*.gguf', 'starcoder*.gguf'],
            'phi2': ['phi-2-*.gguf', 'phi*.gguf'],
            'wizardcoder': ['wizardcoder-*.gguf', 'wizard*.gguf']
        }
        
        # Get patterns for this model
        search_patterns = patterns.get(model_id, [f'{model_id}*.gguf'])
        
        # Search for matching files
        for pattern in search_patterns:
            matches = list(self.models_dir.glob(pattern))
            if matches:
                # Prefer larger models (better quality)
                largest = max(matches, key=lambda p: p.stat().st_size)
                self.logger.info(f"Found model file for {model_id}: {largest.name}")
                return largest
        
        self.logger.warning(f"No model file found for {model_id} in {self.models_dir}")
        return None
    
    def _load_model(self, model_id: str, model_spec: ModelSpec) -> Optional[LlamaCppCodeLLM]:
        """
        Load a GGUF model using llama.cpp
        
        Args:
            model_id: Model identifier
            model_spec: Model specification
            
        Returns:
            Loaded model or None
        """
        # Check if model already loaded
        if model_id in self._loaded_models:
            self.logger.info(f"Using cached model: {model_id}")
            return self._loaded_models[model_id]
        
        # Check if llama.cpp is available
        if LlamaCppCodeLLM is None:
            self.logger.error("llama-cpp-python not available. Install with: pip install llama-cpp-python")
            return None
        
        # Find model file
        model_file = self._find_model_file(model_id)
        if model_file is None:
            return None
        
        try:
            # Load model with llama.cpp
            self.logger.info(f"Loading model: {model_file}")
            model = LlamaCppCodeLLM(
                model_path=str(model_file),
                n_ctx=8192,  # 8K context window
                n_gpu_layers=-1,  # Use GPU if available
                verbose=False
            )
            
            # Cache the model
            self._loaded_models[model_id] = model
            self.logger.info(f"Model loaded successfully: {model_id}")
            return model
            
        except Exception as e:
            self.logger.error(f"Failed to load model {model_id}: {e}")
            return None
    
    def _generate_with_model(
        self,
        model_id: str,
        model_spec: ModelSpec,
        prompt: str,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[List] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7
    ) -> str:
        """
        Generate response using a loaded model
        
        Args:
            model_id: Model identifier
            model_spec: Model specification
            prompt: User prompt
            system_prompt: Optional system prompt
            conversation_history: Optional conversation history
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            
        Returns:
            Generated text
        """
        # Load the model
        model = self._load_model(model_id, model_spec)
        if model is None:
            raise RuntimeError(f"Failed to load model: {model_id}")
        
        # Build the full prompt
        full_prompt = self._build_prompt(
            prompt=prompt,
            system_prompt=system_prompt,
            conversation_history=conversation_history
        )
        
        # Generate config
        if GenerationConfig is None:
            raise RuntimeError("GenerationConfig not available. Install versaai.models.code_llm")
        
        config = GenerationConfig(
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=0.95,
            top_k=50,
            stop_sequences=["```\n", "\n\n\n", "<|endoftext|>"]
        )
        
        # Generate response
        self.logger.info(f"Generating with {model_id}...")
        response = model.generate(full_prompt, config)
        
        return response.strip()
    
    def _build_prompt(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[List] = None
    ) -> str:
        """
        Build the full prompt for the model
        
        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            conversation_history: Optional conversation history
            
        Returns:
            Full formatted prompt
        """
        parts = []
        
        # Add system prompt
        if system_prompt:
            parts.append(f"### System:\n{system_prompt}\n")
        
        # Add conversation history
        if conversation_history:
            for msg in conversation_history:
                role = msg.get('role', 'user')
                content = msg.get('content', '')
                if role == 'user':
                    parts.append(f"### User:\n{content}\n")
                elif role == 'assistant':
                    parts.append(f"### Assistant:\n{content}\n")
        
        # Add current prompt
        parts.append(f"### User:\n{prompt}\n")
        parts.append("### Assistant:\n")
        
        return "\n".join(parts)


# ────────────────────────────────────────────────────────────────────────────
# Budget-Aware Provider Routing (Part 6)
# ────────────────────────────────────────────────────────────────────────────

def route_to_best_provider(
    providers: List[str],
    budget_tokens: int,
    require_tools: bool = True,
    latency_critical: bool = False,
    time_budget_s: Optional[float] = None,
) -> str:
    """
    Route to the best provider based on budget and latency constraints.
    
    Args:
        providers: List of provider names ["groq", "openai", "ollama", ...]
        budget_tokens: Token budget for this request
        require_tools: If True, provider must support tools
        latency_critical: If True, prioritize low-latency providers
        time_budget_s: Max time allowed (seconds), used to filter providers
    
    Returns:
        Selected provider name
    """
    # Provider capability matrix
    provider_matrix = {
        "groq": {
            "avg_latency": 0.5,
            "cost_per_1k": 0.01,
            "supports_tools": True,
            "supports_streaming": True,
        },
        "openai": {
            "avg_latency": 1.0,
            "cost_per_1k": 0.15,
            "supports_tools": True,
            "supports_streaming": True,
        },
        "anthropic": {
            "avg_latency": 1.2,
            "cost_per_1k": 0.08,
            "supports_tools": True,
            "supports_streaming": True,
        },
        "ollama": {
            "avg_latency": 2.0,
            "cost_per_1k": 0.0,
            "supports_tools": False,
            "supports_streaming": True,
        },
    }
    
    # Filter by constraints
    candidates = []
    for provider in providers:
        if provider not in provider_matrix:
            continue
        
        spec = provider_matrix[provider]
        
        # Check tool requirement
        if require_tools and not spec.get("supports_tools", False):
            continue
        
        # Check time budget
        if time_budget_s and spec.get("avg_latency", 0) > time_budget_s:
            continue
        
        candidates.append(provider)
    
    if not candidates:
        # Fallback to first provider if no valid candidate
        return providers[0] if providers else "groq"
    
    # Score candidates
    if latency_critical:
        # Prioritize by latency
        best = min(candidates, key=lambda p: provider_matrix[p].get("avg_latency", 999))
    else:
        # Prioritize by cost efficiency (cost per token given budget)
        best = min(
            candidates,
            key=lambda p: provider_matrix[p].get("cost_per_1k", 0) / max(budget_tokens / 1000, 1)
        )
    
    return best


def can_satisfy_within_budget(
    request_tokens: int,
    budget_tokens: int,
    expected_output_tokens: int,
) -> bool:
    """
    Check if a request can be satisfied within token budget.
    
    Args:
        request_tokens: Tokens in the request/prompt
        budget_tokens: Total available token budget
        expected_output_tokens: Estimated output tokens needed
    
    Returns:
        True if request + output fits within budget, False otherwise
    """
    total_needed = request_tokens + expected_output_tokens
    return total_needed <= budget_tokens


def get_fallback_providers(primary_provider: str) -> List[str]:
    """
    Get a list of fallback providers in priority order when primary fails.
    
    Args:
        primary_provider: The primary provider that failed
    
    Returns:
        List of fallback providers in order of preference
    """
    # Define fallback chains
    fallback_chains = {
        "groq": ["openai", "anthropic", "ollama"],
        "openai": ["anthropic", "groq", "ollama"],
        "anthropic": ["openai", "groq", "ollama"],
        "ollama": ["groq", "openai", "anthropic"],
    }
    
    return fallback_chains.get(primary_provider, ["groq", "openai", "anthropic"])


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Initialize router (assuming 16GB RAM, all models downloaded)
    router = ModelRouter(available_ram_gb=16)
    
    # Test cases
    test_tasks = [
        ("Create a simple function to add two numbers in Python", None, False, False),
        ("Debug this complex algorithm with memory leaks", "c++", False, True),
        ("Refactor entire codebase to use modern JavaScript patterns", "javascript", False, True),
        ("Quick Python script to parse CSV file", "python", True, False),
        ("Implement binary search tree with balancing in Java", "java", False, True),
    ]
    
    print("\n🎯 Model Router Test Cases:\n")
    for task, lang, speed, quality in test_tasks:
        model_id, model = router.select_model(task, lang, speed, quality)
        print(f"Task: {task[:60]}...")
        print(f"  → Selected: {model.name} ({model.tier.value})")
        print(f"  → Reason: {', '.join(model.strengths)}\n")
