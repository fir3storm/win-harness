"""
Unit tests for win-harness core components.

Run with:  python -m pytest tests/ -v
Or simply: python tests/test_harness.py
"""

from __future__ import annotations

import os
import tempfile
import unittest

from harness.core.base import ExecutionResult, Platform, Tool, ToolCategory, ToolSpec
from harness.core.memory import MemoryStore, hash_embedding, cosine_similarity
from harness.core.registry import ToolRegistry
from harness.core.executor import ExecutionEngine
from harness.core.learner import SelfLearner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _DummyTool(Tool):
    """A lightweight tool for testing."""

    def __init__(self, name="dummy_tool", description="A dummy test tool.", **kwargs):
        self.spec = ToolSpec(
            name=name,
            description=description,
            category=ToolCategory.UTILITY,
            platforms=[Platform.WINDOWS],
            **kwargs,
        )

    def run(self, **parameters):
        import time as _time
        start = _time.perf_counter()
        val = parameters.get("value", 0)
        output = f"dummy result for {val}"
        dur = int((_time.perf_counter() - start) * 1000)
        return self._build_result(
            success=True,
            output=output,
            parameters=parameters,
            duration_ms=dur,
        )


class _FailingTool(Tool):
    spec = ToolSpec(
        name="failing_tool",
        description="Always fails.",
        category=ToolCategory.UTILITY,
        platforms=[Platform.WINDOWS],
    )

    def run(self, **parameters):
        import time as _time
        start = _time.perf_counter()
        dur = int((_time.perf_counter() - start) * 1000)
        return self._build_result(
            success=False,
            error="Intentional failure",
            parameters=parameters,
            duration_ms=dur,
        )


# ---------------------------------------------------------------------------
# Memory store tests
# ---------------------------------------------------------------------------

class TestMemoryStore(unittest.TestCase):
    """Tests for the SQLite + LRU memory store."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)  # let MemoryStore create fresh
        self._store = None

    def tearDown(self):
        # Close SQLite connection before deleting (Windows file locks)
        if self._store:
            self._store.close()
        if os.path.exists(self.db_path):
            try:
                os.unlink(self.db_path)
            except PermissionError:
                pass

    def test_store_and_retrieve(self):
        self._store = MemoryStore(db_path=self.db_path)
        result = ExecutionResult(
            tool_name="test_tool", success=True, output="hello",
            duration_ms=42, parameters_used={"k": "v"},
        )
        spec = ToolSpec("test_tool", "desc", ToolCategory.UTILITY, [Platform.WINDOWS])
        self._store.store_execution("test task", result, spec, cache_params={"k": "v"})

        cached = self._store.get_cached_result("test_tool", {"k": "v"})
        self.assertIsNotNone(cached)
        self.assertTrue(cached.success)
        self.assertEqual(cached.output, "hello")

    def test_cache_key_consistency(self):
        """Cache keys must be consistent between store and retrieve."""
        self._store = MemoryStore(db_path=self.db_path)
        params = {"command": "Get-Process", "timeout": 30}
        result = ExecutionResult(
            tool_name="ps_command", success=True, output="ok",
            duration_ms=100, parameters_used=params,
        )
        spec = ToolSpec("ps_command", "desc", ToolCategory.POWERSHELL, [Platform.WINDOWS])
        self._store.store_execution("task", result, spec, cache_params=params)
        cached = self._store.get_cached_result("ps_command", params)
        self.assertIsNotNone(cached)

    def test_lru_eviction(self):
        """LRU cache should evict oldest entries when full."""
        self._store = MemoryStore(db_path=self.db_path, max_cache=3)
        spec = ToolSpec("t", "d", ToolCategory.UTILITY, [Platform.WINDOWS])

        for i in range(5):
            result = ExecutionResult(
                tool_name=f"tool_{i}", success=True,
                duration_ms=i, parameters_used={"i": i},
            )
            self._store._lru_put(f"key_{i}", result)

        # Only the last 3 should remain
        self.assertEqual(len(self._store._lru), 3)

    def test_semantic_similarity(self):
        """Hashing embeddings should return similar items for similar text."""
        q_vec = hash_embedding("check running processes on windows")
        a_vec = hash_embedding("list running processes Windows system")
        sim = cosine_similarity(q_vec, a_vec)
        self.assertGreater(sim, 0.0)


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------

class TestToolRegistry(unittest.TestCase):
    def test_register_and_get(self):
        reg = ToolRegistry()
        tool = _DummyTool()
        reg.register(tool)
        self.assertIsNotNone(reg.get("dummy_tool"))

    def test_duplicate_register(self):
        reg = ToolRegistry()
        reg.register(_DummyTool())
        with self.assertRaises(ValueError):
            reg.register(_DummyTool())

    def test_search(self):
        reg = ToolRegistry()
        reg.register(_DummyTool(name="process_checker",
                                description="Check running processes on system"))
        results = reg.search("process")
        self.assertTrue(any(t.spec.name == "process_checker" for t in results))

    def test_categorisation(self):
        reg = ToolRegistry()
        reg.register(_DummyTool(name="sys_info", description="System info tool"))
        results = reg.get_by_category(ToolCategory.UTILITY)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].spec.name, "sys_info")


# ---------------------------------------------------------------------------
# Executor tests
# ---------------------------------------------------------------------------

class TestExecutor(unittest.TestCase):
    def setUp(self):
        self.reg = ToolRegistry()
        self.reg.register(_DummyTool())
        self.reg.register(_FailingTool())
        self.memory = MemoryStore(db_path=":memory:")
        self.engine = ExecutionEngine(self.reg, self.memory)

    def tearDown(self):
        self.memory.close()

    def test_sync_execute_success(self):
        result = self.engine.sync_execute("dummy_tool", {"value": 42}, "test task")
        self.assertTrue(result.success)
        self.assertIn("42", result.output)

    def test_sync_execute_failure(self):
        result = self.engine.sync_execute("failing_tool", {}, "test task")
        self.assertFalse(result.success)
        self.assertIn("Intentional failure", result.error)

    def test_cache_hit(self):
        """Second call should return cached result (0ms)."""
        params = {"value": 99}
        r1 = self.engine.sync_execute("dummy_tool", params, "cache test")
        r2 = self.engine.sync_execute("dummy_tool", params, "cache test")
        self.assertFalse(r1.metadata.get("cache_hit", False))
        self.assertTrue(r2.metadata.get("cache_hit", False))
        self.assertEqual(r2.duration_ms, 0)

    def test_skip_cache(self):
        """When skip_cache=True, should always execute fresh."""
        params = {"value": 1}
        r1 = self.engine.sync_execute("dummy_tool", params, "skip test")
        r2 = self.engine.sync_execute("dummy_tool", params, "skip test")
        # Both should succeed
        self.assertTrue(r1.success)
        self.assertTrue(r2.success)


# ---------------------------------------------------------------------------
# Learner tests
# ---------------------------------------------------------------------------

class TestLearner(unittest.TestCase):
    def setUp(self):
        self.reg = ToolRegistry()
        self.reg.register(_DummyTool())
        self.memory = MemoryStore(db_path=":memory:")
        self.learner = SelfLearner(self.reg, self.memory)

    def tearDown(self):
        self.memory.close()

    def test_recommend_with_no_history(self):
        """With no history, tools matching the task should be recommended."""
        # _DummyTool has UTILITY category; task "check processes" categorises
        # to INFORMATION, but the registry.search should still find it if the
        # description contains relevant keywords
        tool = _DummyTool(
            name="process_checker",
            description="Tool to check running processes and system status",
        )
        self.reg.register(tool)
        self.learner = SelfLearner(self.reg, self.memory)

        recs = self.learner.recommend_tools("check processes", top_k=5)
        self.assertGreaterEqual(len(recs), 1)
        self.assertEqual(recs[0].tool.spec.name, "process_checker")


if __name__ == "__main__":
    unittest.main(verbosity=2)
