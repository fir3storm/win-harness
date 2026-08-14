# CommandCode Agent Instructions for win-harness

Place this in your project root or CommandCode workspace to teach
CommandCode how to use win-harness.

## Overview

`win-harness` is a memory-enhanced, self-learning tool harness that
bridges CommandCode to Windows security tools (PowerShell, WSL/Kali,
cmd). It persists every execution to SQLite, caches results in an LRU
cache for sub-millisecond repeat lookups, and learns from failures to
optimize future tool selection.

## Installation

```bash
pip install -e .
```

## Usage

### Option 1: CLI Commands (always available)

```bash
# Auto-plan and execute a security task
win-harness plan "Check running processes on Windows"

# Get tool recommendations
win-harness recommend "Check for privilege escalation vectors"

# Run a specific tool
win-harness run ps_command -p command="Get-Process"

# View learned stats
win-harness stats
```

### Option 2: CommandCode Mod (recommended)

Install the mod file:

```bash
mkdir -p ~/.commandcode/mods
cp integrations/commandcode/win-harness.mod.ts ~/.commandcode/mods/
```

Then use in CommandCode:

- `/win_harness_plan "Check running processes on Windows"`
- `/win_harness_recommend "Check for privilege escalation vectors"`
- `/win_harness_run ps_command --param command="Get-Service"`
- `/win_harness_stats`

## Tools Reference

| Command | Description |
|---------|-------------|
| `win-harness plan <task>` | Auto-plan + execute a task with learning |
| `win-harness recommend <task>` | Get tool recommendations with confidence |
| `win-harness run <tool> -p k=v` | Run a specific tool directly |
| `win-harness list` | List all registered tools |
| `win-harness stats` | View memory/performance statistics |
| `win-harness clear-cache` | Clear LRU cache (force fresh results) |

## Tool Details

- **ps_command**: Execute arbitrary PowerShell commands
- **system_info**: Collect OS, CPU, memory, process, service info
- **network_recon**: DNS, port scan, ARP, SMB share enumeration
- **win_credentials**: Wi-Fi passwords, Credential Manager
- **wsl_command**: Run Linux commands in WSL (Kali Linux)
- **kali_tool**: Run specific Kali tools (nmap, sqlmap, nikto, etc.)
