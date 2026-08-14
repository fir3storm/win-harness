#!/usr/bin/env python3
"""
Command-line interface for win-harness.

Usage examples:
    # List available tools
    win-harness list

    # Run a tool directly
    win-harness run ps_command -p command="Get-Process"

    # Let the harness plan + execute automatically
    win-harness plan "Scan local network for open ports"

    # Get tool recommendations for a task
    win-harness recommend "Check for privilege escalation vectors"

    # View memory/stats
    win-harness stats
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from typing import Any

from harness.core.base import ToolSpec
from harness.core.harness import ToolHarness


def _create_harness(args: argparse.Namespace) -> ToolHarness:
    db = args.db or "~/.harness/memory.db"
    return ToolHarness(db_path=db, wsl_distribution=args.distro)


def cmd_list(args: argparse.Namespace) -> int:
    harness = _create_harness(args)
    specs: list[ToolSpec] = harness.list_tools()

    if not specs:
        print("No tools registered.")
        return 0

    print(f"{'NAME':<22} {'CATEGORY':<14} {'PLATFORMS':<20} REQUIRES_ELEV")
    print("-" * 80)
    for s in specs:
        plats = ",".join(p.value for p in s.platforms)
        elev = "YES" if s.requires_elevation else ""
        print(f"{s.name:<22} {s.category.value:<14} {plats:<20} {elev}")

    print(f"\nTotal: {len(specs)} tools")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    harness = _create_harness(args)

    # Parse --param key=value pairs
    params: dict[str, Any] = {}
    for p in args.param or []:
        if "=" in p:
            key, val = p.split("=", 1)
            # Try to parse as JSON, fall back to string
            try:
                params[key] = json.loads(val)
            except (json.JSONDecodeError, ValueError):
                params[key] = val

    result = harness.run(args.tool, params, task_description=args.task or args.tool)

    print(json.dumps(result.to_dict(), indent=2, default=str))

    # Show memory summary
    stats = harness.get_tool_stats(args.tool)
    if stats:
        total = stats.get("success_count", 0) + stats.get("failure_count", 0)
        sr = stats.get("success_rate", 0)
        print(f"\n[{args.tool}] Historical: {stats['success_count']}/{total} successes ({sr:.0%}), "
              f"avg {stats['avg_duration']:.0f}ms")

    return 0 if result.success else 1


def cmd_plan(args: argparse.Namespace) -> int:
    harness = _create_harness(args)
    task = " ".join(args.task_desc) if args.task_desc else ""
    if not task:
        print("Error: no task description provided")
        return 1

    print(f"\n[ANALYZE] Analysing task: {task}\n")

    # Show recommendations
    recs = harness.recommend(task, top_k=5)
    if recs:
        print("[RECOMMEND] Top recommendations:")
        for r in recs:
            print(f"  * {r.tool.spec.name} (confidence: {r.confidence:.0%}) - {r.rationale}")
            if r.suggested_parameters:
                print(f"    Suggested params: {json.dumps(r.suggested_parameters, default=str)}")
        print()

    # Plan and execute
    print("[EXECUTE] Running optimised plan...\n")
    results = harness.plan_and_execute(task)

    for i, r in enumerate(results):
        status = "[OK]" if r.success else "[FAIL]"
        print(f"  {i+1}. {status} {r.tool_name} ({r.duration_ms}ms)")
        if not r.success:
            print(f"     Error: {r.error[:200]}")
        if r.output:
            preview = r.output[:500] + "..." if len(r.output) > 500 else r.output
            print(f"     Output: {preview}")

    # Summary
    successes = sum(1 for r in results if r.success)
    total_time = sum(r.duration_ms for r in results)
    print(f"\n[SUMMARY] {successes}/{len(results)} tools succeeded in {total_time}ms total")

    harness.save()
    return 0 if successes == len(results) else 1


def cmd_recommend(args: argparse.Namespace) -> int:
    harness = _create_harness(args)
    task = " ".join(args.task_desc) if args.task_desc else ""
    if not task:
        print("Error: no task description provided")
        return 1

    recs = harness.recommend(task, top_k=5)
    if not recs:
        print("No recommendations found.")
        return 0

    print(f"Recommendations for: {task}\n")
    for r in recs:
        print(f"  [TOOL] {r.tool.spec.name} (confidence: {r.confidence:.0%})")
        print(f"     Category: {r.tool.spec.category.value}")
        print(f"     Rationale: {r.rationale}")
        print(f"     Estimated time: ~{r.expected_duration_ms}ms")
        if r.suggested_parameters:
            print(f"     Auto-suggested parameters: {json.dumps(r.suggested_parameters, default=str)}")
        print()

    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    harness = _create_harness(args)
    summary = harness.get_memory_summary()

    print("=" * 60)
    print(" win-harness Memory Summary")
    print("=" * 60)
    print(f"  Registered tools:        {summary['total_tools']}")
    print(f"  Total executions:        {summary['total_executions']}")
    print(f"  Total successes:         {summary['total_successes']}")
    print(f"  Total failures:          {summary['total_failures']}")
    sr = summary['success_rate']
    print(f"  Overall success rate:    {sr:.1%}")

    if summary['top_tools']:
        print(f"\n  Top performing tools:")
        print(f"  {'TOOL':<22} {'SUCCESSES':>10} {'FAILURES':>10} {'RATE':>8}")
        print(f"  {'----':<22} {'---------':>10} {'--------':>10} {'----':>8}")
        for t in summary['top_tools']:
            rate = t['success_count'] / (t['success_count'] + t['failure_count']) if (t['success_count'] + t['failure_count']) > 0 else 0
            print(f"  {t['tool_name']:<22} {t['success_count']:>10} {t['failure_count']:>10} {rate:>7.0%}")

    # Tool-specific stats
    if args.tool:
        stats = harness.get_tool_stats(args.tool)
        if stats:
            print(f"\n  Detailed stats for '{args.tool}':")
            for k, v in stats.items():
                print(f"    {k}: {v}")

    return 0


def cmd_clear_cache(args: argparse.Namespace) -> int:
    harness = _create_harness(args)
    count = harness.clear_cache()
    print(f"Cleared {count} cached results.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="win-harness",
        description="Memory-enhanced, self-learning tool harness for Windows security operations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            \

            Examples:
              %(prog)s list
              %(prog)s run ps_command -p command="Get-Process" -t "Check running processes"
              %(prog)s plan "Scan local network for open ports"
              %(prog)s recommend "Check for privilege escalation vectors"
              %(prog)s stats
        """),
    )

    parser.add_argument("--db", type=str, default=None,
                        help="Path to the SQLite memory database (default: ~/.harness/memory.db)")
    parser.add_argument("--distro", type=str, default="kali-linux",
                        help="WSL distribution to use (default: kali-linux)")

    sub = parser.add_subparsers(dest="command", help="Available commands")

    # list
    p_list = sub.add_parser("list", help="List all registered tools")
    p_list.set_defaults(func=cmd_list)

    # run
    p_run = sub.add_parser("run", help="Execute a specific tool")
    p_run.add_argument("tool", help="Tool name to execute")
    p_run.add_argument("--param", "-p", action="append", default=[],
                       help="Tool parameter as key=value (can be repeated)")
    p_run.add_argument("--task", "-t", type=str, default=None,
                       help="Task description for memory context")
    p_run.set_defaults(func=cmd_run)

    # plan
    p_plan = sub.add_parser("plan", help="Let the harness plan and auto-execute a task")
    p_plan.add_argument("task_desc", nargs="*", help="Task description")
    p_plan.set_defaults(func=cmd_plan)

    # recommend
    p_rec = sub.add_parser("recommend", help="Get tool recommendations for a task")
    p_rec.add_argument("task_desc", nargs="*", help="Task description")
    p_rec.set_defaults(func=cmd_recommend)

    # stats
    p_stats = sub.add_parser("stats", help="Show memory and performance statistics")
    p_stats.add_argument("--tool", type=str, default=None,
                         help="Show detailed stats for a specific tool")
    p_stats.set_defaults(func=cmd_stats)

    # clear-cache
    p_clear = sub.add_parser("clear-cache", help="Clear the LRU result cache")
    p_clear.set_defaults(func=cmd_clear_cache)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "func"):
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
