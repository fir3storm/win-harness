"""
Base abstractions for tools and execution results.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Platform(str, Enum):
    WINDOWS = "windows"
    WSL = "wsl"
    POWERSHELL = "powershell"
    CMD = "cmd"
    LINUX = "linux"
    ANY = "any"


class ToolCategory(str, Enum):
    SYSTEM = "system"
    NETWORK = "network"
    FORENSICS = "forensics"
    PRIVILEGE = "privilege"
    INFORMATION = "information"
    UTILITY = "utility"
    WSL_TOOL = "wsl_tool"
    POWERSHELL = "powershell"


@dataclass
class ToolSpec:
    """Static metadata describing a tool, used for discovery and filtering."""
    name: str
    description: str
    category: ToolCategory
    platforms: list[Platform]
    parameters: dict[str, Any] = field(default_factory=dict)
    examples: list[str] = field(default_factory=list)
    requires_elevation: bool = False
    estimated_cost: float = 1.0  # relative cost (1.0 = baseline)


@dataclass
class ExecutionResult:
    """Standardised result returned by every tool execution."""
    tool_name: str
    success: bool
    output: str = ""
    error: str = ""
    duration_ms: int = 0
    exit_code: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    parameters_used: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return self.output if self.success else f"{self.error}\n{self.output}".strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "exit_code": self.exit_code,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
            "parameters_used": self.parameters_used,
        }


class Tool(ABC):
    """
    Abstract base class for all tools.

    Concrete tools implement :meth:`run` (synchronous) or :meth:`arun`
    (asynchronous).  The harness will prefer ``arun`` when available to
    enable parallel execution.
    """

    spec: ToolSpec

    @property
    def should_cache(self) -> bool:
        """Whether results from this tool should be cached."""
        return True

    @property
    def cache_ttl(self) -> int:
        """Cache time-to-live in seconds (0 = cache forever)."""
        return 300

    def params_for_task(self, task_description: str) -> dict[str, Any]:
        """
        Generate default parameters for a task description.

        Override in subclasses to provide intelligent parameter inference.
        The base implementation returns an empty dict — tools that need
        parameters should override this method.
        """
        return {}

    @abstractmethod
    def run(self, **parameters: Any) -> ExecutionResult:
        """Execute the tool synchronously and return an ExecutionResult."""
        ...

    async def arun(self, **parameters: Any) -> ExecutionResult:
        """Asynchronous wrapper — execute via thread pool by default."""
        import asyncio
        return await asyncio.to_thread(self.run, **parameters)

    # Internal helpers --------------------------------------------------

    def _build_result(
        self,
        success: bool,
        output: str = "",
        error: str = "",
        exit_code: int = 0,
        duration_ms: int = 0,
        metadata: Optional[dict[str, Any]] = None,
        parameters: Optional[dict[str, Any]] = None,
    ) -> ExecutionResult:
        return ExecutionResult(
            tool_name=self.spec.name,
            success=success,
            output=output,
            error=error,
            duration_ms=duration_ms,
            exit_code=exit_code,
            metadata=metadata or {},
            parameters_used=parameters or {},
        )
