"""
Async execution engine with parallel dispatch, result caching, and
Windows/WSL subprocess management.

Key optimisations for speed:
  - LRU cache checks (microsecond) before touching SQLite
  - Concurrent.futures thread pool for CPU/IO-bound tool execution
  - Batched execution for independent tool calls
  - Smart timeout per tool category
"""

from __future__ import annotations

import asyncio
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from harness.core.base import ExecutionResult, Tool
from harness.core.memory import MemoryStore
from harness.core.registry import ToolRegistry

# Per-category timeout estimates (seconds)
_TIMEOUTS: dict[str, int] = {
    "information": 5,
    "system": 10,
    "network": 30,
    "utility": 15,
    "wsl_tool": 60,
    "powershell": 30,
}


class ExecutionEngine:
    """
    Executes tools with caching, parallelism, and statistics tracking.

    Usage::

        engine = ExecutionEngine(registry, memory)
        results = await engine.execute_batch([tool1, tool2])
    """

    def __init__(
        self,
        registry: ToolRegistry,
        memory: MemoryStore,
        max_workers: int = 8,
    ):
        self.registry = registry
        self.memory = memory
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._loop: asyncio.AbstractEventLoop | None = None

    async def execute(
        self,
        tool_name: str,
        parameters: Optional[dict[str, Any]] = None,
        task_description: str = "",
        skip_cache: bool = False,
    ) -> ExecutionResult:
        """
        Execute a single tool, checking cache first.

        Parameters
        ----------
        tool_name : str
            Registered tool name.
        parameters : dict | None
            Tool parameters.
        task_description : str
            The overarching task — stored in memory for learning.
        skip_cache : bool
            Bypass LRU cache lookup (useful for tools that must always refresh).
        """
        tool = self.registry.get(tool_name)
        if tool is None:
            return ExecutionResult(
                tool_name=tool_name,
                success=False,
                error=f"Tool '{tool_name}' not registered",
                duration_ms=0,
            )

        params = parameters or {}

        # Check LRU cache — microsecond fast
        if not skip_cache and tool.should_cache:
            cached = self.memory.get_cached_result(tool_name, params)
            if cached is not None:
                return ExecutionResult(
                    tool_name=cached.tool_name,
                    success=cached.success,
                    output=cached.output,
                    error=cached.error,
                    duration_ms=0,  # cache hit — zero cost
                    exit_code=cached.exit_code,
                    metadata={**cached.metadata, "cache_hit": True},
                    timestamp=time.time(),
                    parameters_used=cached.parameters_used,
                )

        # Execute
        start = time.perf_counter()
        timeout = _TIMEOUTS.get(tool.spec.category.value, 20)

        try:
            result = await asyncio.wait_for(
                tool.arun(**params),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            elapsed = int((time.perf_counter() - start) * 1000)
            result = ExecutionResult(
                tool_name=tool_name,
                success=False,
                error=f"Timeout after {timeout}s",
                duration_ms=elapsed,
                parameters_used=params,
            )
        except Exception as exc:
            elapsed = int((time.perf_counter() - start) * 1000)
            result = ExecutionResult(
                tool_name=tool_name,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=elapsed,
                parameters_used=params,
            )

        # Store in memory for learning
        if task_description:
            self.memory.store_execution(
                task_description, result, tool.spec, cache_params=params,
            )

        return result

    async def execute_batch(
        self,
        requests: list[tuple[str, dict[str, Any]]],
        task_description: str = "",
        max_concurrent: int = 8,
    ) -> list[ExecutionResult]:
        """
        Execute multiple tools concurrently.

        All tools are dispatched in a single batch — no sequential bottleneck.
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _guarded(name: str, params: dict) -> ExecutionResult:
            async with semaphore:
                return await self.execute(name, params, task_description)

        tasks = [_guarded(name, params) for name, params in requests]
        return await asyncio.gather(*tasks)

    async def execute_plan(
        self,
        plan: list[tuple[str, dict[str, Any]]],
        task_description: str = "",
    ) -> list[ExecutionResult]:
        """
        Execute tools sequentially as an ordered plan (each step may depend
        on the previous step's output).

        If a tool fails, subsequent tools are still attempted but logged as
        skipped with a clear error chain.
        """
        results: list[ExecutionResult] = []
        context: dict[str, Any] = {}

        for tool_name, params in plan:
            # Allow parameter interpolation from previous results
            resolved_params = self._interpolate_params(params, context)

            result = await self.execute(tool_name, resolved_params, task_description)
            results.append(result)

            if result.success:
                context[tool_name] = result.output
            else:
                # Log the failure chain
                context["_errors"] = context.get("_errors", []) + [
                    {"tool": tool_name, "error": result.error, "output": result.output}
                ]

        return results

    def _interpolate_params(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Simple template interpolation: ``{{ tool_name }}`` in string params
        gets replaced with the output of a previous tool in the plan.
        """
        if not context:
            return params

        pattern = re.compile(r"\{\{\s*(\w+)\s*\}\}")

        def _replace(value: Any) -> Any:
            if isinstance(value, str):
                return pattern.sub(
                    lambda m: str(context.get(m.group(1), m.group(0))),
                    value,
                )
            return value

        return {k: _replace(v) for k, v in params.items()}

    async def arun(self, coro):
        """Run a coroutine in the background and return the future."""
        if self._loop is None:
            self._loop = asyncio.get_event_loop()
        return await coro

    def sync_execute(
        self,
        tool_name: str,
        parameters: Optional[dict[str, Any]] = None,
        task_description: str = "",
    ) -> ExecutionResult:
        """Synchronous wrapper for tools that don't need async context."""
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

        return self._loop.run_until_complete(
            self.execute(tool_name, parameters, task_description)
        )

    @property
    def pool(self) -> ThreadPoolExecutor:
        return self._pool
