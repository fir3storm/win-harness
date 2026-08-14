"""
Concrete tool implementations for Windows security operations:

- PowerShell execution (one-liners, scripts)
- Native cmd tool execution
- System information enumeration
- Network reconnaissance
- WSL/Kali tool orchestration
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

from harness.core.base import ExecutionResult, Platform, Tool, ToolCategory, ToolSpec
from harness.tools.executor import ExecutionBridge, PowerShellExecutor, WSLExecutor


# ---------------------------------------------------------------------------
# PowerShell tools
# ---------------------------------------------------------------------------

class PowerShellTool(Tool):
    """Execute arbitrary PowerShell commands."""

    spec = ToolSpec(
        name="ps_command",
        description="Run a PowerShell command or script block on Windows. Supports all cmdlets, pipelines, and object output.",
        category=ToolCategory.POWERSHELL,
        platforms=[Platform.WINDOWS, Platform.POWERSHELL],
        parameters={
            "command": {"type": "string", "description": "PowerShell command to execute"},
            "timeout": {"type": "integer", "default": 30, "description": "Timeout in seconds"},
        },
        examples=[
            "Get-Process | Where-Object {$_.CPU -gt 100}",
            "Get-Service | Where-Object {$_.Status -eq 'Running'}",
            "Get-WinEvent -LogName Security -MaxEvents 50",
        ],
        requires_elevation=True,
    )

    def __init__(self):
        self._executor = PowerShellExecutor()

    def params_for_task(self, task_description: str) -> dict[str, Any]:
        """Infer a PowerShell command from the task description."""
        desc = task_description.lower()

        # Map common task keywords to PowerShell commands
        if "process" in desc:
            return {"command": "Get-Process | Sort-Object WS -Descending | Select-Object -First 10 ProcessName, Id, WS"}
        if "service" in desc:
            return {"command": "Get-Service | Where-Object {$_.Status -eq 'Running'} | Select-Object -First 10 Name, Status"}
        if "event" in desc or "log" in desc:
            return {"command": "Get-WinEvent -LogName Security -MaxEvents 20 | Select-Object TimeCreated, Id, Message"}
        if "netstat" in desc or "port" in desc or "network" in desc:
            return {"command": "Get-NetTCPConnection | Where-Object {$_.State -eq 'Listen'} | Select-Object LocalAddress, LocalPort, State"}
        if "user" in desc:
            return {"command": "Get-CimInstance Win32_ComputerSystem | Select-Object -ExpandProperty UserName; Get-WmiObject Win32_NetworkLoginProfile | Select-Object Name, LastLogon"}
        # Default: treat the task itself as a command if it looks like PowerShell
        if any(desc.startswith(kw) for kw in ["get-", "set-", "start-", "stop-", "invoke-", "test-", "resolve-", "new-", "remove-", "install-", "uninstall-", "restart-", "get"]):
            return {"command": task_description}
        # If it doesn't match known patterns, return empty (tool will error)
        return {}

    def run(self, **parameters: Any) -> ExecutionResult:
        command = parameters.get("command", "")
        timeout = parameters.get("timeout", 30)
        start = time.perf_counter()

        if not command:
            return ExecutionResult(
                tool_name=self.spec.name,
                success=False,
                error="No command provided",
                duration_ms=int((time.perf_counter() - start) * 1000),
            )

        success, stdout, stderr, exit_code, dur = self._executor.run_ps(
            command, timeout=timeout
        )

        # Try to parse PowerShell object output as JSON for structured results
        metadata = {"exit_code": exit_code}
        output = stdout
        if stdout:
            try:
                parsed = json.loads(stdout.strip())
                if isinstance(parsed, (list, dict)):
                    metadata["structured_output"] = parsed
                    output = json.dumps(parsed, indent=2)
            except (json.JSONDecodeError, ValueError):
                # Raw text output -- keep as-is
                pass

        return ExecutionResult(
            tool_name=self.spec.name,
            success=success,
            output=output,
            error=stderr,
            duration_ms=dur,
            exit_code=exit_code,
            metadata=metadata,
            parameters_used={"command": command, "timeout": timeout},
        )


# ---------------------------------------------------------------------------
# System information tools
# ---------------------------------------------------------------------------

class SystemInfoTool(Tool):
    """Enumerate system information via PowerShell."""

    spec = ToolSpec(
        name="system_info",
        description="Collect system information: OS version, installed patches, running processes, services, network config, and logged-in users.",
        category=ToolCategory.SYSTEM,
        platforms=[Platform.WINDOWS],
        parameters={
            "detail_level": {"type": "string", "enum": ["quick", "full"], "default": "quick"},
        },
        examples=[
            "Collect basic OS and hardware info",
            "Get full system enumeration including processes and services",
        ],
    )

    def params_for_task(self, task_description: str) -> dict[str, Any]:
        """Infer detail level from the task description."""
        desc = task_description.lower()
        if "full" in desc or "complete" in desc or "detailed" in desc or "comprehensive" in desc:
            return {"detail_level": "full"}
        return {"detail_level": "quick"}

    def run(self, **parameters: Any) -> ExecutionResult:
        detail = parameters.get("detail_level", "quick")
        start = time.perf_counter()

        if detail == "full":
            ps_script = """
            $info = @{
                'os'       = Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber, LastBootUpTime
                'cpu'      = Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors
                'memory'   = Get-CimInstance Win32_PhysicalMemory | Measure-Object -Property Capacity -Sum | Select-Object @{N='TotalGB';E={[math]::Round($_.Sum/1GB,2)}}
                'processes'= (Get-Process | Select-Object ProcessName, Id, WorkingSet | Sort-Object WorkingSet -Descending | Select-Object -First 20)
                'services' = Get-Service | Where-Object {$_.Status -eq 'Running'} | Select-Object Name, DisplayName, Status
                'users'    = Get-CimInstance Win32_ComputerSystem | Select-Object -ExpandProperty UserName
            }
            $info | ConvertTo-Json -Depth 5
            """
        else:
            ps_script = """
            $info = @{
                'os'     = (Get-CimInstance Win32_OperatingSystem).Caption
                'version'= (Get-CimInstance Win32_OperatingSystem).Version
                'arch'   = (Get-CimInstance Win32_Processor).AddressWidth
                'users'  = (Get-CimInstance Win32_ComputerSystem).UserName
            }
            $info | ConvertTo-Json -Compress
            """

        success, stdout, stderr, exit_code, dur = PowerShellExecutor.run_ps(
            ps_script, timeout=60 if detail == "full" else 15
        )

        metadata = {"detail_level": detail}
        try:
            parsed = json.loads(stdout.strip())
            metadata["structured"] = parsed
        except (json.JSONDecodeError, ValueError):
            pass

        return ExecutionResult(
            tool_name=self.spec.name,
            success=success,
            output=stdout,
            error=stderr,
            duration_ms=dur,
            exit_code=exit_code,
            metadata=metadata,
            parameters_used={"detail_level": detail},
        )


# ---------------------------------------------------------------------------
# Network recon tools
# ---------------------------------------------------------------------------

class NetworkReconTool(Tool):
    """Windows network reconnaissance (built-in tools only, no nmap dependency)."""

    spec = ToolSpec(
        name="network_recon",
        description="Perform network reconnaissance using built-in Windows tools: resolve hostnames, check open ports, enumerate shares, query routing table, and inspect ARP table.",
        category=ToolCategory.NETWORK,
        platforms=[Platform.WINDOWS],
        parameters={
            "target": {"type": "string", "description": "Target hostname, IP, or CIDR range"},
            "check_ports": {"type": "boolean", "default": True, "description": "Check common ports via PS"},
            "resolve_dns": {"type": "boolean", "default": True, "description": "Resolve DNS records for target"},
            "check_shares": {"type": "boolean", "default": False, "description": "Enumerate SMB shares"},
        },
        examples=[
            "Scan target 192.168.1.1 for open ports",
            "Resolve DNS for example.com and check common ports",
        ],
        requires_elevation=True,
    )

    def run(self, **parameters: Any) -> ExecutionResult:
        target = parameters.get("target", "")
        check_ports = parameters.get("check_ports", True)
        resolve_dns = parameters.get("resolve_dns", True)
        check_shares = parameters.get("check_shares", False)

        start = time.perf_counter()
        if not target:
            return ExecutionResult(
                tool_name=self.spec.name,
                success=False,
                error="No target specified",
                duration_ms=int((time.perf_counter() - start) * 1000),
                parameters_used=parameters,
            )

        results: dict[str, Any] = {}

        # DNS resolution
        if resolve_dns:
            cmd = f"Resolve-DnsName -Name '{target}' -ErrorAction SilentlyContinue | ConvertTo-Json"
            success, out, err, code, dur = PowerShellExecutor.run_ps(cmd)
            results["dns"] = {"success": success, "output": out, "error": err}

        # Port check -- use Test-NetConnection for common ports
        if check_ports:
            ports = "21,22,23,25,53,80,110,135,139,143,443,445,465,587,993,995,3306,3389,5432,6379,8080,8443"
            cmd = (
                "$results = @(); "
                f"foreach($p in '{ports}'.Split(',')){{ "
                f"  $r = Test-NetConnection -ComputerName '{target}' -Port $p "
                "  -WarningAction SilentlyContinue; "
                "  $results += [PSCustomObject]@{Port=$p; Open=$r.TcpTestSucceeded} "
                "}; "
                "$results | Where-Object {$_.Open} | ConvertTo-Json"
            )
            success, out, err, code, dur = PowerShellExecutor.run_ps(cmd, timeout=120)
            results["ports"] = {"success": success, "output": out, "error": err}

        # SMB shares
        if check_shares:
            cmd = f"Get-SmbShare -ComputerName '{target}' -ErrorAction SilentlyContinue | Select-Object Name, Path, Description | ConvertTo-Json"
            success, out, err, code, dur = PowerShellExecutor.run_ps(cmd, timeout=15)
            results["shares"] = {"success": success, "output": out, "error": err}

        # ARP / routing table
        arp_cmd = "Get-NetNeighbor | Where-Object {$_.State -ne 'Permanent'} | Select-Object IPAddress, LinkLayerAddress, InterfaceAlias | ConvertTo-Json"
        success, out, err, code, dur = PowerShellExecutor.run_ps(arp_cmd, timeout=10)
        results["arp"] = {"success": success, "output": out, "error": err}

        duration_ms = int((time.perf_counter() - start) * 1000)
        output = json.dumps(results, indent=2, default=str)

        all_success = all(r["success"] for r in results.values())
        return ExecutionResult(
            tool_name=self.spec.name,
            success=all_success,
            output=output,
            duration_ms=duration_ms,
            metadata={"results": results},
            parameters_used=parameters,
        )


# ---------------------------------------------------------------------------
# WSL / Kali tools
# ---------------------------------------------------------------------------

class WSLCommandTool(Tool):
    """Execute commands inside a WSL distribution (e.g., Kali Linux)."""

    spec = ToolSpec(
        name="wsl_command",
        description="Run a Linux command inside a WSL distribution. Defaults to Kali Linux. Leverages full Linux tool suite (nmap, sqlmap, nikto, etc.).",
        category=ToolCategory.WSL_TOOL,
        platforms=[Platform.WSL, Platform.LINUX],
        parameters={
            "command": {"type": "string", "description": "Linux command to execute inside WSL"},
            "timeout": {"type": "integer", "default": 60, "description": "Timeout in seconds"},
            "user": {"type": "string", "default": "", "description": "User to run as (empty = default)"},
            "working_dir": {"type": "string", "default": "", "description": "Working directory in WSL"},
        },
        examples=[
            "nmap -sT -p- 192.168.1.1",
            "sqlmap --url=http://example.com/id=1 --batch --dump",
            "nikto -h http://example.com",
        ],
    )

    def __init__(self, distribution: str = "kali-linux"):
        self._executor = WSLExecutor(distribution=distribution)

    def params_for_task(self, task_description: str) -> dict[str, Any]:
        """Infer a Linux command from the task description."""
        desc = task_description.lower()

        if "nmap" in desc or "port scan" in desc or "open port" in desc:
            return {"command": "nmap -sT -p- 127.0.0.1"}
        if "process" in desc or "ps" in desc:
            return {"command": "ps aux --sort=-%mem | head -20"}
        if "network" in desc or "netstat" in desc or "listening" in desc:
            return {"command": "netstat -tlnp 2>/dev/null || ss -tlnp"}
        if "whoami" in desc or "user" in desc or "id" in desc:
            return {"command": "whoami; id; uname -a"}
        if "disk" in desc or "filesystem" in desc:
            return {"command": "df -h"}
        # Default: treat the task as a shell command
        return {"command": task_description}

    def run(self, **parameters: Any) -> ExecutionResult:
        command = parameters.get("command", "")
        timeout = parameters.get("timeout", 60)
        user = parameters.get("user", "")
        working_dir = parameters.get("working_dir", "")

        start = time.perf_counter()

        if not command:
            return ExecutionResult(
                tool_name=self.spec.name,
                success=False,
                error="No command provided",
                duration_ms=int((time.perf_counter() - start) * 1000),
                parameters_used=parameters,
            )

        if not self._executor.check_wsl_available():
            return ExecutionResult(
                tool_name=self.spec.name,
                success=False,
                error=f"WSL or distribution '{self._executor.distribution}' not available",
                duration_ms=int((time.perf_counter() - start) * 1000),
                parameters_used=parameters,
            )

        success, stdout, stderr, exit_code, dur = self._executor.run_wsl(
            command, timeout=timeout, user=user, working_dir=working_dir,
        )

        return ExecutionResult(
            tool_name=self.spec.name,
            success=success,
            output=stdout,
            error=stderr,
            duration_ms=dur,
            exit_code=exit_code,
            metadata=dict(self._executor.__dict__),
            parameters_used=parameters,
        )


class KaliTool(Tool):
    """Run a specific Kali Linux security tool through WSL."""

    spec = ToolSpec(
        name="kali_tool",
        description="Run a named Kali Linux security tool (nmap, sqlmap, nikto, enum4linux, etc.) inside WSL with smart argument construction.",
        category=ToolCategory.WSL_TOOL,
        platforms=[Platform.WSL],
        parameters={
            "tool": {"type": "string", "description": "Kali tool name (nmap, sqlmap, nikto, enum4linux, dirb, gobuster, etc.)"},
            "args": {"type": "string", "description": "Tool arguments (excluding the tool name)"},
            "timeout": {"type": "integer", "default": 120, "description": "Timeout in seconds"},
        },
        examples=[
            "Run nmap with service detection on 192.168.1.1",
            "Run sqlmap against http://example.com/page?id=1 --batch --dump",
            "Run enum4linux on target 192.168.1.100",
        ],
        requires_elevation=True,
    )

    def __init__(self, distribution: str = "kali-linux"):
        self._executor = WSLExecutor(distribution=distribution)

    def params_for_task(self, task_description: str) -> dict[str, Any]:
        """Infer a Kali tool name and args from the task description."""
        desc = task_description.lower()

        # Map common security task patterns to tool + args
        if "nmap" in desc or "port scan" in desc or "open port" in desc:
            target = self._extract_target(desc)
            return {"tool": "nmap", "args": f"-sT -sV {target}"}
        if "sqlmap" in desc or "sql injection" in desc:
            target = self._extract_target(desc, default="http://example.com")
            return {"tool": "sqlmap", "args": f"--url={target} --batch"}
        if "nikto" in desc or "web vuln" in desc or "web scan" in desc:
            target = self._extract_target(desc, default="http://example.com")
            return {"tool": "nikto", "args": f"-h {target}"}
        if "enum4linux" in desc or "smb" in desc:
            target = self._extract_target(desc)
            return {"tool": "enum4linux", "args": f"-a {target}"}
        if "dirb" in desc or "gobuster" in desc or "dir" in desc:
            target = self._extract_target(desc, default="http://example.com")
            return {"tool": "gobuster", "args": f"dir -u {target} -w /usr/share/wordlists/dirb/common.txt"}
        # Default: try nmap with a generic target
        return {"tool": "nmap", "args": "-sT 127.0.0.1"}

    @staticmethod
    def _extract_target(text: str, default: str = "127.0.0.1") -> str:
        """Extract an IP or URL from text, falling back to default."""
        ip_match = re.search(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b", text)
        if ip_match:
            return ip_match.group(1)
        url_match = re.search(r"\b(https?://[^\s]+)", text)
        if url_match:
            return url_match.group(1)
        return default

    def run(self, **parameters: Any) -> ExecutionResult:
        tool_name = parameters.get("tool", "")
        args = parameters.get("args", "")
        timeout = parameters.get("timeout", 120)

        start = time.perf_counter()

        if not tool_name:
            return ExecutionResult(
                tool_name=self.spec.name,
                success=False,
                error="No tool specified",
                duration_ms=int((time.perf_counter() - start) * 1000),
                parameters_used=parameters,
            )

        command = f"{tool_name} {args}".strip()

        if not self._executor.check_wsl_available():
            return ExecutionResult(
                tool_name=self.spec.name,
                success=False,
                error=f"WSL distribution '{self._executor.distribution}' not available",
                duration_ms=int((time.perf_counter() - start) * 1000),
                parameters_used=parameters,
            )

        success, stdout, stderr, exit_code, dur = self._executor.run_wsl(
            command, timeout=timeout,
        )

        return ExecutionResult(
            tool_name=self.spec.name,
            success=success,
            output=stdout,
            error=stderr,
            duration_ms=dur,
            exit_code=exit_code,
            metadata={"kali_tool": tool_name, "args": args},
            parameters_used=parameters,
        )


# ---------------------------------------------------------------------------
# Credential access tools (Windows-native, no external deps)
# ---------------------------------------------------------------------------

class WindowsCredentialTool(Tool):
    """Enumerate stored Windows credentials using built-in PowerShell cmdlets."""

    spec = ToolSpec(
        name="win_credentials",
        description="Enumerate Windows stored credentials: saved Wi-Fi profiles, RDP connections, and credential manager entries. Uses only built-in Windows APIs.",
        category=ToolCategory.PRIVILEGE,
        platforms=[Platform.WINDOWS],
        parameters={
            "scan_wifi": {"type": "boolean", "default": True, "description": "Scan saved Wi-Fi profiles and their keys"},
            "scan_credman": {"type": "boolean", "default": True, "description": "Scan Windows Credential Manager"},
            "scan_rdp": {"type": "boolean", "default": False, "description": "Scan saved RDP connections"},
        },
        examples=[
            "Extract all saved Wi-Fi passwords",
            "Retrieve Credential Manager entries",
        ],
        requires_elevation=True,
    )

    def params_for_task(self, task_description: str) -> dict[str, Any]:
        """Infer scan options from the task description."""
        desc = task_description.lower()
        return {
            "scan_wifi": "wifi" in desc or "wireless" in desc or "password" in desc,
            "scan_credman": True,
            "scan_rdp": "rdp" in desc,
        }

    def run(self, **parameters: Any) -> ExecutionResult:
        scan_wifi = parameters.get("scan_wifi", True)
        scan_credman = parameters.get("scan_credman", True)
        scan_rdp = parameters.get("scan_rdp", False)

        start = time.perf_counter()
        results: dict[str, Any] = {}

        if scan_wifi:
            # Get all Wi-Fi profiles and their keys
            ps_script = """
            $profiles = netsh wlan show profiles | Select-String ":(.+)$" | ForEach-Object { $_.Line.Substring($_.Line.LastIndexOf(':')).Trim(' :') }
            $creds = @()
            foreach ($profile in $profiles) {
                $key = netsh wlan show profile name="$profile" key=clear 2>$null | Select-String "Key Content" | ForEach-Object { $_.Line.Substring($_.Line.LastIndexOf(':')).Trim(' :') }
                $creds += [PSCustomObject]@{SSID=$profile; Key=($key -join '')}
            }
            $creds | ConvertTo-Json -Compress
            """
            success, out, err, code, dur = PowerShellExecutor.run_ps(ps_script, timeout=30)
            results["wifi"] = {"success": success, "output": out, "error": err}

        if scan_credman:
            # Use PowerShell to access credential manager (limited without elevation)
            ps_script = """
            cmdkey /list 2>&1 | Out-String
            """
            success, out, err, code, dur = PowerShellExecutor.run_ps(ps_script, timeout=10)
            results["credman"] = {"success": success, "output": out, "error": err}

        duration_ms = int((time.perf_counter() - start) * 1000)
        output = json.dumps(results, indent=2, default=str)

        return ExecutionResult(
            tool_name=self.spec.name,
            success=True,  # Partial success if any part worked
            output=output,
            duration_ms=duration_ms,
            metadata={"scanned": list(results.keys())},
            parameters_used=parameters,
        )
