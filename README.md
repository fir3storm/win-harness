<div align="center">

# 🇮🇳 win-harness

### **Memory-Enhanced, Self-Learning Tool Harness for Windows**

**Part of the "Made in India" initiative — Open-sourced for India's Independence Day, 15th August 2026**

[![Python](https://img.shields.io/badge/python-3.10+-blue?style=flat-square&logo=python)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey?style=flat-square&logo=windows)](https://microsoft.com/windows)
[![Built in India](https://img.shields.io/badge/built%20in-india-orange?style=flat-square)](https://github.com/fir3storm/win-harness)
[![Open Source](https://img.shields.io/badge/open%20source-❤%EF%B8%8F-red?style=flat-square)](LICENSE)

---

### 🚀 One Command. Any Security Task.

```bash
pip install win-harness
win-harness plan "Check running processes on Windows"
```

> **ज्ञानं ज्ञेयं विज्ञानं चास्य विद्धि मे प्रभो।**
> *"Know the knowable, the knowledge, and the knower — the path to liberation."*

---

</div>

## ✨ What Is It?

`win-harness` is a **memory-enhanced, self-learning tool harness** that bridges AI agents to Windows security tools (PowerShell, WSL/Kali, cmd). It's like having a security analyst in your CLI that learns from every task you give it.

### Three Core Pillars

| 🧠 **Memory** | ⚡ **Speed** | 🤖 **Self-Learning** |
|---|---|---|
| SQLite persistence with semantic recall | Async parallel execution, LRU cache (0ms hits) | Learns from success/failure, adapts recommendations |

---

## 🚦 Quick Start

### Install Globally
```bash
pip install win-harness
# or clone + install from source:
git clone https://github.com/fir3storm/win-harness.git
cd win-harness && pip install -e .
```

### Run a Task
```bash
# Let the harness auto-plan and execute
win-harness plan "Check running processes on Windows"

# Get tool recommendations
win-harness recommend "Check for privilege escalation vectors"

# Run a specific tool
win-harness run ps_command -p command="Get-Process | Select-Object -First 5"

# Check what the harness has learned
win-harness stats
```

### Use the Python API
```python
from harness.core.harness import ToolHarness

h = ToolHarness()

# Auto-plan + execute (parameter inference built-in)
results = h.plan_and_execute("Check running processes on Windows")

# Get recommendations with confidence scores
for r in h.recommend("Check for privilege escalation vectors"):
    print(f"{r.tool.spec.name} ({r.confidence:.0%}) — {r.rationale}")

# View memory summary
print(h.get_memory_summary())
```

---

## 🛠️ Built-In Tools

| Tool | Category | Platforms | Parameters Auto-Inferred |
|------|----------|-----------|--------------------------|
| `ps_command` | PowerShell | Windows, PowerShell | ✅ *"processes" → `Get-Process`* |
| `system_info` | System | Windows | ✅ *"full" → full detail scan |
| `network_recon` | Network | Windows | ✅ *"port scan" → Test-NetConnection |
| `win_credentials` | Privilege | Windows | ✅ *"wifi" → scan Wi-Fi profiles |
| `wsl_command` | WSL | WSL, Linux | ✅ *"nmap" → `nmap -sT 127.0.0.1`* |
| `kali_tool` | WSL | WSL | ✅ *"sqlmap" → extracts target from task* |

---

## 🎯 Usage Scenarios

### 1. Incident Response — Triage Suspicious Activity

When an AI SOC agent detects anomalous behaviour (e.g., a suspicious process in EDR alerts), it can immediately triage the affected host:

```bash
win-harness plan "Check running processes and network connections for suspicious activity"
```

**What happens:** The harness recommends `ps_command` (high confidence from past success), auto-infers `Get-Process | Sort-Object WS -Descending | Select-Object -First 10` and `Get-NetTCPConnection | Where-Object {$_.State -eq 'Listen'}`, executes both, and caches results. On repeat queries within 5 minutes, responses are served from LRU cache (0ms).

### 2. Privilege Escalation Assessment

An AI agent assessing a compromised endpoint can enumerate credential stores and privilege paths:

```bash
win-harness plan "Check for privilege escalation vectors on this Windows machine"
```

**What happens:** The harness recommends `win_credentials` (auto-infers Wi-Fi + Credential Manager scan) and `system_info` (full detail level). It runs `netsh wlan show profile` to extract saved Wi-Fi passwords, `cmdkey /list` for stored credentials, and `Get-CimInstance Win32_ComputerSystem` for logged-in users — all via built-in tools, no external dependencies.

### 3. Network Reconnaissance via WSL/Kali

When an AI agent needs Linux security tools (nmap, sqlmap, etc.) but is running on Windows:

```bash
win-harness plan "Scan 192.168.1.0/24 for open ports using nmap"
```

**What happens:** The harness recommends `kali_tool`, auto-infers `{"tool": "nmap", "args": "-sTV 192.168.1.0/24"}` by extracting the target IP from the task description, and executes `wsl -d kali-linux -e nmap -sT -sV 192.168.1.0/24`. If WSL/Kali isn't installed, it fails fast with a clear error and the learner lowers that tool's confidence for similar future tasks.

---

## 🤖 AI Agent Integration

### CommandCode (Slash Commands)
```bash
# After installing the mod file:
~/.commandcode/mods/win-harness.mod.ts → copy here

# Then use:
/win-harness-plan "Check running processes on Windows"
/win-harness-run ps_command --param command="Get-Service"
```

### Codex CLI
```bash
# Direct shell integration
win-harness plan "Enumerate network connections"

# Or use the provided config
codex --config integrations/codex/win-harness.codex.yaml
```

### Claude Code
```bash
# Invoke via Bash tool
win-harness recommend "Check for privilege escalation vectors"
win-harness stats
```

---

## 🏗️ Architecture

```
win-harness/
├── harness/
│   ├── core/
│   │   ├── base.py        — Tool abstractions, specs, results
│   │   ├── registry.py    — Discovery, fuzzy search, filtering
│   │   ├── memory.py      — SQLite + hashing embeddings + LRU
│   │   ├── executor.py    — Async engine with caching
│   │   ├── learner.py     — Recommendations + plan optimisation
│   │   └── harness.py     — Main orchestrator
│   ├── tools/
│   │   ├── executor.py    — Windows/PowerShell/WSL subprocess bridge
│   │   └── windows_tools.py — 5 built-in tool implementations
│   ├── cli.py             — CLI interface
│   └── __main__.py        — Package entry point
├── integrations/
│   ├── commandcode/       — Ready-to-use mod + AGENTS.md
│   └── codex/             — Agent prompts + config
├── tests/                 — 13 unit tests
├── install.sh / .bat      — One-command global install
└── README.md
```

---

## 📦 How Self-Learning Works

1. **Every execution** is logged to SQLite with the task description, tool used, parameters, success/failure, and duration
2. **Semantic recall** uses feature-hashing embeddings (no ML dependencies) to find similar past tasks
3. **Recommendation engine** scores tools by: 40% success rate + 30% experience + 20% speed + 10% base
4. **Plan optimization** replaces failing tools, removes duplicates, adapts timeouts
5. **Parameter inference** maps natural language to tool parameters automatically

```
Task: "Check running processes on Windows"

Harness recommends:
  • ps_command (77% confidence) — High success rate, fast, similar to 3 past tasks
  → Auto-infers: {"command": "Get-Process | Sort-Object WS -Descending | ..."}
  → Executes: ✅ 628ms
  → Caches: 0ms on repeat calls
```

---

## 📜 License

**MIT — Open Sourced for India's Independence Day 🇮🇳**

> As part of the "Made in India" initiative, this tool is released as open source
> on 15th August 2026. Built with ❤️ in India.

---

**Created by Abhirup Guha, Info Security Solution**

Contributions welcome! Open an issue or submit a pull request.

---

<div align="center">

**🇮🇳 **जय हिंद** — Happy Independence Day!**

</div>
