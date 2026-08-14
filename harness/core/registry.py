"""
Tool registry: discover, register, and look up tools by name, category,
or platform.  Provides fast prefix-matching and fuzzy search.
"""

from __future__ import annotations

import re
from typing import Optional

from harness.core.base import (
    ExecutionResult,
    Platform,
    Tool,
    ToolCategory,
    ToolSpec,
)


class ToolRegistry:
    """In-memory registry of all available tools with fast lookup."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._by_category: dict[ToolCategory, list[str]] = {}
        self._by_platform: dict[Platform, list[str]] = {}

    # -- registration ----------------------------------------------------

    def register(self, tool: Tool) -> None:
        """Register a tool.  Raises ValueError if name conflicts."""
        name = tool.spec.name
        if name in self._tools:
            raise ValueError(f"Tool '{name}' already registered")

        self._tools[name] = tool

        cat = tool.spec.category
        self._by_category.setdefault(cat, []).append(name)

        for plat in tool.spec.platforms:
            self._by_platform.setdefault(plat, []).append(name)

    def unregister(self, name: str) -> bool:
        """Remove a tool by name.  Returns True if found."""
        tool = self._tools.pop(name, None)
        if tool is None:
            return False

        self._by_category.get(tool.spec.category, []).remove(name)
        for plat in tool.spec.platforms:
            names = self._by_platform.get(plat, [])
            if name in names:
                names.remove(name)
        return True

    # -- lookup ----------------------------------------------------------

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def get_spec(self, name: str) -> Optional[ToolSpec]:
        tool = self._tools.get(name)
        return tool.spec if tool else None

    def list(self) -> list[str]:
        """Return all registered tool names."""
        return sorted(self._tools.keys())

    def list_specs(self) -> list[ToolSpec]:
        """Return specs for all registered tools."""
        return [t.spec for t in self._tools.values()]

    def get_by_category(self, category: ToolCategory | str) -> list[Tool]:
        cat = ToolCategory(category) if isinstance(category, str) else category
        names = self._by_category.get(cat, [])
        return [self._tools[n] for n in names if n in self._tools]

    def get_by_platform(self, platform: Platform | str) -> list[Tool]:
        plat = Platform(platform) if isinstance(platform, str) else platform
        names = self._by_platform.get(plat, [])
        return [self._tools[n] for n in names if n in self._tools]

    # -- discovery -------------------------------------------------------

    def search(self, query: str) -> list[Tool]:
        """
        Fuzzy search tools by name, description, and examples.

        Uses token overlap with underscore/hyphen splitting and substring
        matching for high recall on compound tool names.
        """
        q_tokens = set(re.findall(r"[a-z0-9_]+", query.lower()))
        if not q_tokens:
            return []

        results: list[tuple[int, Tool]] = []

        for tool in self._tools.values():
            spec = tool.spec
            # Split name on underscores/hyphens for compound names like "process_checker"
            name_tokens = set(re.findall(r"[a-z0-9_]+", spec.name.lower()))
            desc_tokens = set(re.findall(r"[a-z0-9_]+", spec.description.lower()))
            example_tokens: set[str] = set()
            for ex in spec.examples:
                example_tokens.update(re.findall(r"[a-z0-9_]+", ex.lower()))

            all_tokens = name_tokens | desc_tokens | example_tokens

            # Direct token overlap
            score = len(q_tokens & all_tokens)

            # Substring matching: check if any query token is a substring of any tool token
            for q in q_tokens:
                for t in all_tokens:
                    if q in t or t in q:
                        score += 1
                        break

            if score > 0:
                # Bonus if name matches directly
                if q_tokens & name_tokens:
                    score += 3
                results.append((score, tool))

        results.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in results]

    def get_specs_for_task(self, task_keywords: set[str]) -> list[ToolSpec]:
        """Return tool specs whose descriptions match any task keyword."""
        specs: list[tuple[int, ToolSpec]] = []
        for tool in self._tools.values():
            spec = tool.spec
            desc_tokens = set(re.findall(r"[a-z0-9_]+", spec.description.lower())) | set(re.findall(r"[a-z0-9_]+", spec.name.lower()))
            match_count = len(task_keywords & desc_tokens)
            if match_count > 0:
                specs.append((match_count, spec))
        specs.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in specs]
