"""
Low-level subprocess execution for Windows, WSL, and PowerShell.

Uses Windows' native APIs where possible for speed (CreateProcess via
subprocess), and leverages WSL interop for Linux tools inside WSL.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Native (cmd / direct) executor
# ---------------------------------------------------------------------------


class NativeExecutor:
    """Execute commands natively on Windows via cmd or direct binary calls."""

    @staticmethod
    def run_command(
        command: str,
        shell: bool = True,
        timeout: int = 30,
        cwd: Optional[str] = None,
        capture_output: bool = True,
        env: Optional[dict[str, str]] = None,
    ) -> tuple[bool, str, str, int]:
        """
        Run a Windows command synchronously.

        Returns (success, stdout, stderr, exit_code).
        """
        start = time.perf_counter()
        try:
            proc = subprocess.run(
                command if shell else [command],
                shell=shell,
                timeout=timeout,
                capture_output=capture_output,
                text=True,
                cwd=cwd,
                env=env,
            )
            duration_ms = int((time.perf_counter() - start) * 1000)
            success = proc.returncode == 0
            return success, proc.stdout or "", proc.stderr or "", proc.returncode, duration_ms
        except subprocess.TimeoutExpired:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return False, "", f"Timeout after {timeout}s", -1, duration_ms
        except FileNotFoundError as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return False, "", str(exc), -1, duration_ms

    @staticmethod
    async def arun_command(
        command: str,
        timeout: int = 30,
        cwd: Optional[str] = None,
    ) -> tuple[bool, str, str, int]:
        """Async version of run_command using a thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            NativeExecutor.run_command,
            command, True, timeout, cwd, True, None,
        )

    @staticmethod
    def find_tool(name: str) -> Optional[str]:
        """Resolve a tool path on PATH or common Windows locations."""
        return shutil.which(name)


# ---------------------------------------------------------------------------
# PowerShell executor
# ---------------------------------------------------------------------------


class PowerShellExecutor:
    """Execute PowerShell commands with full cmdlet support."""

    PS_PATHS = [
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        r"C:\Windows\System32\PowerShell\7\pwsh.exe",
    ]

    @classmethod
    def _find_powershell(cls) -> str:
        """Locate pwsh.exe or powershell.exe."""
        pwsh = shutil.which("pwsh") or shutil.which("powershell")
        if pwsh:
            return pwsh
        for path in cls.PS_PATHS:
            if shutil.which(path) or __import__("os").path.isfile(path):
                return path
        # Fallback — let cmd resolve it
        return "powershell"

    @classmethod
    def run_ps(
        cls,
        command: str,
        timeout: int = 30,
        encoded: bool = False,
    ) -> tuple[bool, str, str, int]:
        """
        Execute a PowerShell command.

        Parameters
        ----------
        command : str
            PowerShell script or one-liner.
        timeout : int
            Max execution time in seconds.
        encoded : bool
            If True, encode the command as Base64 to bypass quoting issues.
        """
        ps_exe = cls._find_powershell()

        if encoded:
            import base64
            encoded_cmd = base64.b64encode(command.encode("utf-16-le")).decode()
            full_cmd = [ps_exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded_cmd]
        else:
            # Use -Command with proper escaping
            full_cmd = [ps_exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]

        start = time.perf_counter()
        try:
            proc = subprocess.run(
                full_cmd,
                timeout=timeout,
                capture_output=True,
                text=True,
            )
            duration_ms = int((time.perf_counter() - start) * 1000)
            success = proc.returncode == 0
            return success, proc.stdout, proc.stderr, proc.returncode, duration_ms
        except subprocess.TimeoutExpired:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return False, "", f"Timeout after {timeout}s", -1, duration_ms
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return False, "", str(exc), -1, duration_ms

    @classmethod
    async def arun_ps(cls, command: str, timeout: int = 30) -> tuple[bool, str, str, int]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, cls.run_ps, command, timeout, False)


# ---------------------------------------------------------------------------
# WSL executor
# ---------------------------------------------------------------------------


class WSLExecutor:
    """Execute commands inside WSL distributions (default: Kali Linux)."""

    def __init__(self, distribution: str = "kali-linux"):
        self.distribution = distribution

    def run_wsl(
        self,
        command: str,
        timeout: int = 60,
        user: str = "",
        working_dir: str = "",
    ) -> tuple[bool, str, str, int]:
        """
        Run a command inside the specified WSL distribution.

        Parameters
        ----------
        command : str
            Linux shell command to execute inside WSL.
        timeout : int
            Max execution time in seconds.
        user : str
            If set, run as this user: ``wsl -u <user> -e <command>``.
        working_dir : str
            Working directory inside WSL (Linux path).
        """
        parts = ["wsl", "-d", self.distribution, "-e"]
        if user:
            parts = ["wsl", "-d", self.distribution, "-u", user, "-e"]
        if working_dir:
            # Use --cd to set working directory
            parts = parts[:3] + ["--cd", working_dir] + parts[3:]

        parts.append(command)

        start = time.perf_counter()
        try:
            proc = subprocess.run(
                parts,
                timeout=timeout,
                capture_output=True,
                text=True,
            )
            duration_ms = int((time.perf_counter() - start) * 1000)
            success = proc.returncode == 0
            return success, proc.stdout, proc.stderr, proc.returncode, duration_ms
        except subprocess.TimeoutExpired:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return False, "", f"Timeout after {timeout}s", -1, duration_ms
        except FileNotFoundError:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return False, "", "wsl.exe not found -- WSL not installed", -1, duration_ms
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return False, "", str(exc), -1, duration_ms

    async def arun_wsl(
        self,
        command: str,
        timeout: int = 60,
        user: str = "",
        working_dir: str = "",
    ) -> tuple[bool, str, str, int]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.run_wsl, command, timeout, user, working_dir,
        )

    def check_wsl_available(self) -> bool:
        """Quick check whether WSL and the target distribution are available."""
        try:
            proc = subprocess.run(
                ["wsl", "-l", "-v"],
                capture_output=True, text=True, timeout=5
            )
            return proc.returncode == 0 and self.distribution in (proc.stdout or "")
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Unified dispatch
# ---------------------------------------------------------------------------


class ExecutionBridge:
    """
    Unified dispatch layer — routes commands to the right executor based
    on platform tags, with built-in caching of tool availability checks.
    """

    _availability_cache: dict[str, bool] = {}

    def __init__(self, wsl_distribution: str = "kali-linux"):
        self.native = NativeExecutor()
        self.powershell = PowerShellExecutor()
        self.wsl = WSLExecutor(distribution=wsl_distribution)

    async def dispatch(
        self,
        command: str,
        platform: str = "windows",
        timeout: int = 30,
    ) -> dict[str, Any]:
        """
        Dispatch a command to the appropriate executor.

        Returns a dict with: success, stdout, stderr, exit_code, duration_ms.
        """
        if platform == "wsl":
            success, stdout, stderr, code, dur = await self.wsl.arun_wsl(command, timeout)
        elif platform == "powershell":
            success, stdout, stderr, code, dur = await self.powershell.arun_ps(command, timeout)
        else:  # windows / native
            success, stdout, stderr, code, dur = await self.native.arun_command(command, timeout)

        return {
            "success": success,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": code,
            "duration_ms": dur,
        }
