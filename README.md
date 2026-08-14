# win-harness

**Created by Abhirup Guha, Info Security Solution**

A **memory-enhanced, self-learning tool harness** for Windows security operations.

Bridges AI agents to system tools (PowerShell, WSL/Kali, cmd) with three key capabilities:

1. **Memory** — Every tool execution is persisted to SQLite with semantic recall via fast hashing-based embeddings. Results are cached in an in-memory LRU for sub-millisecond repeat lookups.
2. **Speed** — Async parallel execution, concurrent tool dispatch, thread-pool subprocess management, and WAL-mode SQLite for blazing-fast throughput.
3. **Self-Learning** — The learner analyses execution history to recommend optimal tools, suggest successful parameters, optimise tool-chain ordering, and adapt timeouts — improving automatically over time.

## Installation

```bash
pip install -e .
```

## Quick Start

```python
from harness.core.harness import ToolHarness

h = ToolHarness()

# Run a tool directly
result = h.run("ps_command", {"command": "Get-Process | Select-Object -First 5"})
print(result.output)

# Or let the harness plan + execute automatically
results = h.plan_and_execute("Scan local network for open ports")

# Get recommendations
recs = h.recommend("Check for privilege escalation vectors")
for r in recs:
    print(f"{r.tool.spec.name} (confidence: {r.confidence:.0%})")

# View memory
print(h.get_memory_summary())
```

## CLI

```bash
# List available tools
win-harness list

# Run a tool directly
win-harness run ps_command -p command="Get-Process"

# Let the harness plan and auto-execute
win-harness plan "Scan local network for open ports"

# Get tool recommendations
win-harness recommend "Check for privilege escalation vectors"

# Show memory/performance stats
win-harness stats
```

## Built-in Tools

| Tool | Category | Description |
|------|----------|-------------|
| `ps_command` | PowerShell | Execute arbitrary PowerShell commands |
| `system_info` | System | Collect OS, CPU, memory, process, service info |
| `network_recon` | Network | DNS, port scan, ARP, SMB share enumeration |
| `win_credentials` | Privilege | Wi-Fi passwords, Credential Manager |
| `wsl_command` | WSL | Run Linux commands in WSL (Kali Linux) |
| `kali_tool` | WSL | Run specific Kali tools (nmap, sqlmap, nikto, etc.) |

## Architecture

```
harness/
├── core/
│   ├── base.py        — Tool abstractions, ExecutionResult, specs
│   ├── registry.py    — Tool discovery, search, filtering
│   ├── memory.py      — SQLite memory store + hashing embeddings + LRU cache
│   ├── executor.py    — Async execution engine with caching
│   ├── learner.py     — Recommendation engine + plan optimisation
│   └── harness.py     — Main orchestrator (your entry point)
├── tools/
│   ├── executor.py   — Windows/PowerShell/WSL subprocess bridge
│   └── windows_tools.py — Concrete Windows/PowerShell/WSL/Kali tool impls
├── cli.py            — Command-line interface
└── __main__.py       — Package entry point
```

## Memory System

- **SQLite** with WAL mode for durable storage across sessions
- **Hashing-based embeddings** (no ML dependencies) for semantic similarity search
- **LRU cache** (4096 entries) for microsecond repeated-result lookups
- **Tool statistics** — success rates, avg duration, parameter patterns

## Self-Learning

The learner uses a hybrid scoring system:

- **Success rates** from execution history
- **Experience bonus** (confidence grows with more data)
- **Inverse duration** (faster tools score higher)
- **Category matching** (keyword → tool category)
- **Semantic recall** (similar past tasks → recommended tools)
- **Parameter suggestion** (reuse successful parameter sets + infer from task description)

Plans are optimised by:

- Reordering for parallelism where possible
- Replacing underperforming tools with better alternatives
- Removing duplicate/redundant tool calls
- Adapting timeouts based on historical performance

## Usage with AI Code Generators

`win-harness` is designed to be invoked by AI coding agents as an **MCP-style tool provider** or via **shell delegation**. Below are patterns for three popular terminal AI assistants.

### CommandCode (MCP Mod)

Register `win-harness` as a custom mod that exposes tools to the agent context. Create a mod file at `~/.commandcode/mods/win-harness.mod.ts`:

```typescript
import { ModApi } from '@commandcode/api';
import { execSync } from 'child_process';

export default async function winHarnessMod(api: ModApi) {
  // Expose a tool that runs win-harness plan
  api.registerTool(
    'win_harness_plan',
    'Run a security task through the self-learning harness',
    async (task: string) => {
      const result = execSync(`win-harness plan "${task}"`, { encoding: 'utf-8' });
      return result;
    }
  );

  // Expose a tool for direct PowerShell execution
  api.registerTool(
    'win_harness_ps',
    'Execute a PowerShell command through the harness',
    async (command: string) => {
      const result = execSync(`win-harness run ps_command -p command="${command}"`, { encoding: 'utf-8' });
      return result;
    }
  );

  // Expose stats for introspection
  api.registerTool(
    'win_harness_stats',
    'Show harness memory and performance statistics',
    async () => {
      return execSync(`win-harness stats`, { encoding: 'utf-8' });
    }
  );
}
```

Then use it in CommandCode:

```
User: /win_harness_plan "Check running processes on Windows"
```

### Codex CLI

Use the `shell` function in your Codex configuration or just invoke directly:

```bash
# Ask Codex: "Check what processes are running with high memory usage"
# Codex will run:
win-harness plan "Check what processes are running with high memory usage"
```

The harness will:
1. Analyse the task description
2. Recommend the best tools (using memory + keywords)
3. Execute the plan, learning from each step
4. Return structured results for further reasoning

### Claude Code (Anthropic)

Use the `Bash` tool to invoke `win-harness` and feed results back into the conversation:

```bash
# Get recommendations
win-harness recommend "Check for privilege escalation vectors"

# Auto-plan and execute
win-harness plan "Check for privilege escalation vectors"

# Run a specific tool
win-harness run ps_command -p command="Get-Service | Where Status -eq Running"

# Check learned stats
win-harness stats
```

You can also import the Python API directly in a Claude Code-managed script:

```python
from harness.core.harness import ToolHarness
h = ToolHarness()

# Let the harness decide what to run
results = h.plan_and_execute("Check running processes on Windows")
for r in results:
    print(f"[{'OK' if r.success else 'FAIL'}] {r.tool_name}")
    print(r.output[:200])
```

### MCP Server Mode (Advanced)

For full MCP integration, expose `win-harness` as a lightweight MCP server:

```python
# mcp_server.py
import asyncio
from harness.core.harness import ToolHarness

h = ToolHarness()

async def handle_tool_call(name, arguments):
    if name == "harness_plan":
        results = h.plan_and_execute(arguments["task"])
        return [r.to_dict() for r in results]
    elif name == "harness_run":
        result = h.run(arguments["tool"], arguments.get("params", {}), arguments.get("task", ""))
        return result.to_dict()
    elif name == "harness_recommend":
        recs = h.recommend(arguments["task"])
        return [{"tool": r.tool.spec.name, "confidence": r.confidence, "params": r.suggested_parameters} for r in recs]
    elif name == "harness_stats":
        return h.get_memory_summary()
```

Register this MCP server in your AI assistant's config to get `win-harness` tools natively integrated into the agent's tool set.

---

## License

MIT

**Created by Abhirup Guha, Info Security Solution**
