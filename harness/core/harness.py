"""
The main ToolHarness — orchestrates registry, memory, executor, and learner.

This is the primary entry point for users.  It provides both a simple
``run()`` method for ad-hoc tool execution and a ``plan_and_execute()``
method that uses the self-learning layer to automatically select and
optimise the best tool chain for a task.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

from harness.core.base import ExecutionResult, Tool, ToolSpec
from harness.core.executor import ExecutionEngine
from harness.core.learner import OptimisedPlan, SelfLearner, ToolRecommendation
from harness.core.memory import MemoryStore
from harness.core.registry import ToolRegistry


class ToolHarness:
    """
    Unified interface to the memory-enhanced, self-learning tool harness.

    Example::

        harness = ToolHarness(db_path="~/.harness/memory.db")
        result = harness.run("ps_command", {"command": "Get-Process"})

        # Or let the harness plan + execute automatically:
        results = harness.plan_and_execute("Scan local network for open ports")
    """

    def __init__(
        self,
        db_path: str = "~/.harness/memory.db",
        max_workers: int = 8,
        wsl_distribution: str = "kali-linux",
    ):
        self.registry = ToolRegistry()
        self.memory = MemoryStore(db_path=os.path.expanduser(db_path))
        self.engine = ExecutionEngine(self.registry, self.memory, max_workers)
        self.learner = SelfLearner(self.registry, self.memory)
        self._wsl_dist = wsl_distribution
        self._auto_register_tools()

    def _auto_register_tools(self) -> None:
        """Auto-register all built-in Windows tools."""
        from harness.tools.windows_tools import (
            KaliTool,
            PowerShellTool,
            SystemInfoTool,
            WSLCommandTool,
            WindowsCredentialTool,
        )

        tools = [
            PowerShellTool(),
            SystemInfoTool(),
            WSLCommandTool(distribution=self._wsl_dist),
            KaliTool(distribution=self._wsl_dist),
            WindowsCredentialTool(),
        ]

        for tool in tools:
            try:
                self.registry.register(tool)
            except ValueError:
                # Already registered — skip
                pass

    # -- basic execution -------------------------------------------------

    def register(self, tool: Tool) -> None:
        """Register a custom tool."""
        self.registry.register(tool)

    def run(
        self,
        tool_name: str,
        parameters: Optional[dict[str, Any]] = None,
        task_description: str = "",
    ) -> ExecutionResult:
        """Synchronously execute a single tool."""
        return self.engine.sync_execute(tool_name, parameters, task_description)

    async def arun(
        self,
        tool_name: str,
        parameters: Optional[dict[str, Any]] = None,
        task_description: str = "",
    ) -> ExecutionResult:
        """Asynchronously execute a single tool."""
        return await self.engine.execute(tool_name, parameters, task_description)

    async def run_batch(
        self,
        requests: list[tuple[str, dict[str, Any]]],
        task_description: str = "",
        max_concurrent: int = 8,
    ) -> list[ExecutionResult]:
        """Execute multiple tools concurrently."""
        return await self.engine.execute_batch(requests, task_description, max_concurrent)

    async def run_plan(
        self,
        plan: list[tuple[str, dict[str, Any]]],
        task_description: str = "",
    ) -> list[ExecutionResult]:
        """Execute a sequential plan with parameter interpolation."""
        return await self.engine.execute_plan(plan, task_description)

    # -- self-learning execution -----------------------------------------

    def recommend(
        self,
        task_description: str,
        top_k: int = 3,
    ) -> list[ToolRecommendation]:
        """Get tool recommendations for a task description."""
        return self.learner.recommend_tools(task_description, top_k)

    def optimise_plan(
        self,
        task_description: str,
        initial_plan: list[str],
    ) -> OptimisedPlan:
        """Optimise a tool chain based on learned patterns."""
        return self.learner.optimise_plan(task_description, initial_plan)

    def plan_and_execute(
        self,
        task_description: str,
        max_tools: int = 5,
    ) -> list[ExecutionResult]:
        """
        Automatically: recommend tools -> optimise -> execute sequentially.

        This is the highest-level entry point.  The harness will:
        1. Analyse the task description
        2. Recommend the best tools (using memory + keywords)
        3. Optimise the plan (reorder, replace underperforming tools)
        4. Execute the plan, learning from each step
        """
        # Step 1: Recommend
        recs = self.recommend(task_description, top_k=max_tools)
        if not recs:
            # Fallback: try information + system gathering
            recs = self.recommend(task_description, top_k=3)

        # Step 2: Optimise
        plan_names = [r.tool.spec.name for r in recs]
        optimised = self.learner.optimise_plan(task_description, plan_names)

        # Step 3: Execute
        results = self._run_plan_sync(optimised, recs, task_description)

        # Step 4: Learn from the outcome
        for result, rec in zip(results, recs):
            self.learner.learn_from_execution(
                task_description, result.tool_name, result.success, result.duration_ms
            )

        return results

    def _run_plan_sync(
        self,
        optimised: OptimisedPlan,
        recs: list[ToolRecommendation],
        task_description: str,
    ) -> list[ExecutionResult]:
        """Execute an optimised plan synchronously."""
        # Re-create recs mapping for parameter suggestions
        rec_map = {r.tool.spec.name: r for r in recs}

        plan: list[tuple[str, dict[str, Any]]] = []
        for name in optimised.tool_names:
            rec = rec_map.get(name)
            params = rec.suggested_parameters if rec and rec.suggested_parameters else {}

            # Fallback: infer parameters from the task description
            if not params:
                tool = self.registry.get(name)
                if tool:
                    params = tool.params_for_task(task_description)

            plan.append((name, params))

        return self._sync_plan(plan, task_description)

    def _sync_plan(
        self,
        plan: list[tuple[str, dict[str, Any]]],
        task_description: str,
    ) -> list[ExecutionResult]:
        """Run a plan synchronously on the event loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                self.engine.execute_plan(plan, task_description)
            )
        finally:
            loop.close()

    # -- introspection ---------------------------------------------------

    def list_tools(self) -> list[ToolSpec]:
        """List all registered tools."""
        return self.registry.list_specs()

    def get_tool_stats(self, tool_name: str) -> Optional[dict[str, Any]]:
        """Get aggregated stats for a tool."""
        return self.memory.get_tool_stats(tool_name)

    def get_memory_summary(self) -> dict[str, Any]:
        """Get a summary of the memory store."""
        top = self.memory.get_top_tools(10)
        total_execs = len(top)
        total_successes = sum(t["success_count"] for t in top)
        total_failures = sum(t["failure_count"] for t in top)

        return {
            "total_tools": len(self.registry.list_specs()),
            "total_executions": total_successes + total_failures,
            "total_successes": total_successes,
            "total_failures": total_failures,
            "success_rate": total_successes / (total_successes + total_failures) if (total_successes + total_failures) > 0 else 0,
            "top_tools": top,
        }

    def save(self) -> None:
        """Force-save all pending memory to disk."""
        self.memory.checkpoint()

    def clear_cache(self) -> int:
        """Clear the LRU result cache."""
        return self.memory.clear_cache()

    def close(self) -> None:
        """Close resources."""
        self.memory.close()
