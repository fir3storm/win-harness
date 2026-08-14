"""
win-harness: A memory-enhanced, self-learning tool harness for Windows.

Bridges AI agents to system tools (PowerShell, WSL, cmd) with:
- Persistent memory via SQLite with semantic recall
- Async parallel execution for blazing-fast throughput
- Self-learning from execution history to optimize future runs
"""

from harness.core.harness import ToolHarness

__version__ = "1.0.0"
__all__ = ["ToolHarness"]
