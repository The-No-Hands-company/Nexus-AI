from typing import TYPE_CHECKING

from ._version import __api_version__, __min_server_version__, __version__
from .client import AgentListing, AgentTrace, NexusAIClient, NexusAIError, StreamChunk
from .compat import CompatReport, CompatibilityError, assert_compatible, validate
from .operator import NexusOperator, OperatorConfig, RetryConfig

if TYPE_CHECKING:
	from .async_client import AsyncNexusAIClient

validate_compat = validate

__all__ = [
	"AgentListing",
	"AgentTrace",
	"AsyncNexusAIClient",
	"CompatReport",
	"CompatibilityError",
	"NexusAIClient",
	"NexusAIError",
	"NexusOperator",
	"OperatorConfig",
	"RetryConfig",
	"StreamChunk",
	"__api_version__",
	"__min_server_version__",
	"__version__",
	"assert_compatible",
	"validate",
	"validate_compat",
]


def __getattr__(name: str):
	if name == "AsyncNexusAIClient":
		from .async_client import AsyncNexusAIClient

		return AsyncNexusAIClient
	raise AttributeError(name)
