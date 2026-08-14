"""
Self-learning layer: analyses execution history to:

- Recommend the best tool for a given task (based on past success rates)
- Suggest optimal parameters from historically-successful runs
- Optimise tool-chain ordering and identify redundant steps
- Adapt timeouts and retry strategies per tool

All learnings are persisted back to the MemoryStore for cross-session
improvement.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from harness.core.base import Tool, ToolCategory, ToolSpec
from harness.core.memory import MemoryStore
from harness.core.registry import ToolRegistry

# Re-export Platform for the learner module
from harness.core.base import Platform


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ToolRecommendation:
    """A recommended tool with confidence and rationale."""
    tool: Tool
    confidence: float  # 0.0 – 1.0
    rationale: str
    suggested_parameters: dict[str, Any] = field(default_factory=dict)
    expected_duration_ms: int = 0


@dataclass
class OptimisedPlan:
    """An optimised execution plan for a task."""
    tool_names: list[str]
    reasoning: str
    confidence: float
    estimated_total_ms: int
    rationale: str


# ---------------------------------------------------------------------------
# Learner
# ---------------------------------------------------------------------------


class SelfLearner:
    """
    Builds heuristics from execution history to optimise future runs.

    The learner maintains lightweight in-memory models that are refreshed
    lazily from SQLite, so lookups stay sub-millisecond even with thousands
    of historical executions.
    """

    # Keyword -> category mapping for initial tool selection
    _KEYWORD_CATEGORIES: dict[str, ToolCategory] = {
        # System
        "system": ToolCategory.SYSTEM, "os": ToolCategory.SYSTEM,
        "uptime": ToolCategory.SYSTEM, "hostname": ToolCategory.SYSTEM,
        "whoami": ToolCategory.SYSTEM, "users": ToolCategory.SYSTEM,
        "memory": ToolCategory.SYSTEM, "cpu": ToolCategory.SYSTEM,

        # Network
        "port": ToolCategory.NETWORK, "scan": ToolCategory.NETWORK,
        "nmap": ToolCategory.NETWORK, "connect": ToolCategory.NETWORK,
        "firewall": ToolCategory.NETWORK, "ip": ToolCategory.NETWORK,
        "dns": ToolCategory.NETWORK, "http": ToolCategory.NETWORK,
        "net": ToolCategory.NETWORK, "listening": ToolCategory.NETWORK,

        # PowerShell
        "powershell": ToolCategory.POWERSHELL, "ps": ToolCategory.POWERSHELL,
        "get-": ToolCategory.POWERSHELL, "invoke-": ToolCategory.POWERSHELL,

        # WSL
        "wsl": ToolCategory.WSL_TOOL, "bash": ToolCategory.WSL_TOOL,
        "kali": ToolCategory.WSL_TOOL, "linux": ToolCategory.WSL_TOOL,

        # Forensics
        "volatility": ToolCategory.FORENSICS, "vol": ToolCategory.FORENSICS,
        "malfind": ToolCategory.FORENSICS, "timeline": ToolCategory.FORENSICS,
        "artifact": ToolCategory.FORENSICS,

        # Privilege
        "privilege": ToolCategory.PRIVILEGE, "admin": ToolCategory.PRIVILEGE,
        "escalat": ToolCategory.PRIVILEGE, "token": ToolCategory.PRIVILEGE,
        "mimikatz": ToolCategory.PRIVILEGE, "hash": ToolCategory.PRIVILEGE,
        "cred": ToolCategory.PRIVILEGE, "password": ToolCategory.PRIVILEGE,

        # Information
        "info": ToolCategory.INFORMATION, "list": ToolCategory.INFORMATION,
        "enum": ToolCategory.INFORMATION, "find": ToolCategory.INFORMATION,
        "search": ToolCategory.INFORMATION, "query": ToolCategory.INFORMATION,
        "process": ToolCategory.INFORMATION, "service": ToolCategory.INFORMATION,
    }

    def __init__(self, registry: ToolRegistry, memory: MemoryStore):
        self.registry = registry
        self.memory = memory
        self._stats_cache: dict[str, dict[str, Any]] = {}
        self._stats_cache_time: float = 0
        self._cache_ttl: int = 10  # seconds

    # -- internal helpers ------------------------------------------------

    def _refresh_stats_cache(self, force: bool = False) -> None:
        """Lazily refresh aggregated tool stats from SQLite."""
        now = time.time()
        if not force and (now - self._stats_cache_time) < self._cache_ttl:
            return

        self._stats_cache.clear()
        for spec in self.registry.list_specs():
            stats = self.memory.get_tool_stats(spec.name)
            if stats:
                self._stats_cache[spec.name] = stats
        self._stats_cache_time = now

    def _categorise_task(self, description: str) -> list[ToolCategory]:
        """Map a task description to likely tool categories via keyword match."""
        desc_lower = description.lower()
        categories: set[ToolCategory] = set()

        for keyword, cat in self._KEYWORD_CATEGORIES.items():
            if keyword in desc_lower:
                categories.add(cat)

        # Broad coverage: if nothing matched, suggest information + utility
        if not categories:
            categories = {ToolCategory.INFORMATION, ToolCategory.SYSTEM}

        return list(categories)

    def _extract_keywords(self, description: str) -> set[str]:
        """Extract alphanumeric keywords from a task description."""
        return set(re.findall(r"[a-z0-9_]+", description.lower()))

    # -- public API ------------------------------------------------------

    def recommend_tools(
        self,
        task_description: str,
        top_k: int = 3,
    ) -> list[ToolRecommendation]:
        """
        Recommend the best tools for a task, ranked by learned performance.

        Uses a hybrid of:
        1. Historical success rates from the memory store
        2. Category matching from task keywords
        3. Semantic recall of similar past tasks
        """
        self._refresh_stats_cache()
        categories = self._categorise_task(task_description)
        keywords = self._extract_keywords(task_description)

        recommendations: list[tuple[float, ToolRecommendation]] = []

        # Get candidate tools from category + keyword search
        candidate_tools: set[Tool] = set()
        for cat in categories:
            candidate_tools.update(self.registry.get_by_category(cat))
        candidate_tools.update(self.registry.search(" ".join(keywords)))

        # Also check semantically similar past executions
        similar = self.memory.find_similar_executions(task_description, top_k=5)
        similar_tools = {item["tool_name"] for item in similar}
        for name in similar_tools:
            tool = self.registry.get(name)
            if tool:
                candidate_tools.add(tool)

        for tool in candidate_tools:
            spec = tool.spec
            stats = self._stats_cache.get(spec.name, {})

            # Base score from historical success rate
            success_rate = stats.get("success_rate", 0.5)
            exec_count = stats.get("success_count", 0) + stats.get("failure_count", 0)
            avg_duration = stats.get("avg_duration", 2000)

            # Confidence grows with more historical data
            experience_bonus = min(exec_count / 20.0, 1.0)  # saturates at 20 runs

            # Category match bonus
            cat_match = 1.3 if spec.category in categories else 0.8
            # Platform preference: prefer windows-native for Windows tasks
            plat_bonus = 1.2 if Platform.WINDOWS in spec.platforms else 1.0

            confidence = (
                0.4 * success_rate  # 40% weight on success rate
                + 0.3 * experience_bonus  # 30% weight on experience
                + 0.2 * (1.0 / (1.0 + avg_duration / 5000.0))  # 20% inverse duration
                + 0.1  # base
            ) * cat_match * plat_bonus
            confidence = min(confidence, 1.0)

            # Suggest parameters from successful historic runs
            suggested_params: dict[str, Any] = {}
            if exec_count > 3:
                successful = self.memory.get_successful_params(spec.name, task_description)
                if successful:
                    suggested_params = successful[0]

            # Fallback: use params_for_task if no historical params
            if not suggested_params:
                suggested_params = tool.params_for_task(task_description)

            rationale = self._build_rationale(
                spec, success_rate, avg_duration, cat_match, similar,
            )

            recommendations.append((confidence, ToolRecommendation(
                tool=tool,
                confidence=confidence,
                rationale=rationale,
                suggested_parameters=suggested_params,
                expected_duration_ms=int(avg_duration),
            )))

        recommendations.sort(key=lambda x: x[0], reverse=True)
        return [rec for _, rec in recommendations[:top_k]]

    def _build_rationale(
        self,
        spec: ToolSpec,
        success_rate: float,
        avg_duration: float,
        cat_match: float,
        similar: list[dict[str, Any]],
    ) -> str:
        parts: list[str] = []

        if success_rate >= 0.8:
            parts.append(f"High success rate ({success_rate:.0%})")
        elif success_rate < 0.3:
            parts.append(f"Low success rate ({success_rate:.0%})")

        if avg_duration < 500:
            parts.append("fast")
        elif avg_duration > 5000:
            parts.append("slow but high-value")

        if cat_match >= 1.0:
            parts.append(f"matches category '{spec.category.value}'")

        if similar:
            parts.append(f"similar to {len(similar)} past executions")

        return "; ".join(parts) if parts else "New tool with no history"

    def optimise_plan(
        self,
        task_description: str,
        initial_plan: list[str],
    ) -> OptimisedPlan:
        """
        Optimise a tool chain: reorder for parallelism, remove redundant tools,
        and suggest replacements for underperforming tools.
        """
        self._refresh_stats_cache()
        recommendations = self.recommend_tools(task_description)

        optimised: list[str] = []
        reasoning: list[str] = []
        total_ms = 0

        for name in initial_plan:
            tool = self.registry.get(name)
            if tool is None:
                reasoning.append(f"Skipped unregistered tool: {name}")
                continue

            stats = self._stats_cache.get(name, {})
            success_rate = stats.get("success_rate", 0.5)
            avg_dur = stats.get("avg_duration", 2000)

            if success_rate < 0.3 and recommendations:
                # Replace underperforming tool with a recommended alternative
                replacement = next(
                    (r for r in recommendations if r.tool.spec.category == tool.spec.category),
                    recommendations[0],
                )
                reasoning.append(
                    f"Replaced '{name}' (success: {success_rate:.0%}) "
                    f"-> '{replacement.tool.spec.name}' (success: high)"
                )
                optimised.append(replacement.tool.spec.name)
                total_ms += replacement.expected_duration_ms
            else:
                optimised.append(name)
                total_ms += avg_dur

            if avg_dur > 5000:
                reasoning.append(f"'{name}' is slow ({avg_dur:.0f}ms) — consider caching")

        # Deduplicate tools that may have been added twice
        seen: set[str] = set()
        deduped: list[str] = []
        for name in optimised:
            if name not in seen:
                seen.add(name)
                deduped.append(name)
        if len(deduped) < len(optimised):
            reasoning.append(f"Removed {len(optimised) - len(deduped)} duplicate tool(s)")

        confidence = 0.85 if recommendations else 0.5
        reasoning.append(f"Optimised from {len(initial_plan)} -> {len(deduped)} tools")

        return OptimisedPlan(
            tool_names=deduped,
            reasoning="\n".join(reasoning),
            confidence=confidence,
            estimated_total_ms=total_ms,
            rationale=f"Based on {len(recommendations)} recommendations from learned patterns",
        )

    def learn_from_execution(
        self,
        task_description: str,
        tool_name: str,
        success: bool,
        duration_ms: int,
    ) -> None:
        """
        Update in-memory models after a tool execution.

        The persistence already happened in the executor — this method
        refreshes the cache so the next recommendation uses the new data.
        """
        self._refresh_stats_cache(force=True)

    def get_adaptive_timeout(self, tool_name: str) -> int:
        """
        Suggest a timeout for a tool based on its historical performance.

        Uses 3x the historical average duration, clamped to [5, 120] seconds.
        """
        self._refresh_stats_cache()
        stats = self._stats_cache.get(tool_name)
        if stats and stats.get("avg_duration"):
            return max(5, min(120, int(stats["avg_duration"] / 1000 * 3)))
        return 30  # default
