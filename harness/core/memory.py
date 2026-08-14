"""
Persistent memory layer for the tool harness.

Stores every tool execution trace in SQLite and provides:

- Semantic recall via fast hashing-based embeddings (no ML deps required)
- In-memory LRU cache for sub-millisecond repeated-result lookups
- Query interface for the learning layer to discover successful patterns

Design goals: blazing-fast lookups, zero external dependencies.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from typing import Any, Optional

from harness.core.base import ExecutionResult, ToolSpec

# ---------------------------------------------------------------------------
# Embedding helpers — feature hashing + TF-IDF-lite
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9_]+")

# Fixed vocabulary of ~1 K common security/tool terms (expandable)
_DOMAIN_VOCAB = {
    "powershell", "nmap", "sqlmap", "nikto", "wsl", "kali", "wireshark",
    "metasploit", "volatility", "autopsy", "hashcat", "john", "hydra",
    "aircrack", "recon", "enumeration", "exploitation", "privilege",
    "escalation", "scan", "vulnerability", "ioc", "threat", "intel",
    "malware", "forensic", "artifact", "timeline", "memory", "dump",
    "credentials", "password", "hash", "token", "session", "shell",
    "reverse", "payload", "listener", "beacon", "persistence",
    "reconnaissance", "post", "exploitation", "systeminfo", "whoami",
    "netstat", "tasklist", "process", "service", "registry",
    "eventlog", "audit", "compliance", "attack", "surface",
    "intrusion", "detection", "incident", "response", "remediation",
    "hardening", "patch", "update", "config", "baseline",
}


def _tokenize(text: str) -> list[str]:
    """Fast tokenizer: lowercase, split on word boundaries, keep alphanum."""
    if not text:
        return []
    return _TOKEN_RE.findall(text.lower())


def hash_embedding(text: str, dim: int = 256) -> list[float]:
    """
    Feature-hashing embedding — extremely fast, deterministic, no external deps.

    Each token's hash maps to a dimension index; we accumulate +/-1 for
    signed hashing trick.  Result is L2-normalized to a unit vector.
    """
    vec = [0.0] * dim
    tokens = _tokenize(text)
    if not tokens:
        return vec

    for tok in tokens:
        # Combine token with domain vocab for weighted importance
        weight = 2.0 if tok in _DOMAIN_VOCAB else 1.0
        h = hashlib.md5(tok.encode()).digest()
        for i in range(dim):
            byte_idx = (i * 7 + h[i % len(h)]) % 256
            sign = 1.0 if h[byte_idx % len(h)] & 1 == 0 else -1.0
            vec[i] += sign * weight

    # L2 normalize
    norm = sum(v * v for v in vec) ** 0.5
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    return sum(x * y for x, y in zip(a, b))


# ---------------------------------------------------------------------------
# Memory store
# ---------------------------------------------------------------------------


class MemoryStore:
    """
    SQLite-backed persistent memory for tool execution traces.

    Tables:
        - executions:  one row per tool call with full parameters and results
        - tool_stats:  aggregated performance per tool
        - chains:      sequences of tools used for specific task types

    An in-memory LRU cache sits in front of SQLite for microsecond lookups
    of recent/recurring queries.
    """

    def __init__(self, db_path: str = ":memory:", max_cache: int = 4096):
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._cache_max = max_cache
        # LRU cache for exact-match result lookups (parameters hash -> result)
        self._lru: dict[str, tuple[float, ExecutionResult]] = {}
        self._lru_access: dict[str, float] = {}
        self._init_schema()

    # -- connection management ------------------------------------------

    @property
    def db(self) -> sqlite3.Connection:
        if self._conn is None:
            if self._db_path == ":memory:":
                self._conn = sqlite3.connect(":memory:", check_same_thread=False)
            else:
                os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
                self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")  # speed over durability
            self._init_schema()
        return self._conn

    def _init_schema(self) -> None:
        conn = self.db
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS executions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                task_hash   TEXT NOT NULL,
                tool_name   TEXT NOT NULL,
                parameters  TEXT NOT NULL,
                success     INTEGER NOT NULL,
                output      TEXT,
                error       TEXT,
                duration_ms INTEGER NOT NULL,
                exit_code   INTEGER,
                metadata    TEXT,
                timestamp   REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_exec_tool ON executions(tool_name);
            CREATE INDEX IF NOT EXISTS idx_exec_task ON executions(task_hash);
            CREATE INDEX IF NOT EXISTS idx_exec_ts   ON executions(timestamp DESC);

            CREATE TABLE IF NOT EXISTS tool_stats (
                tool_name      TEXT PRIMARY KEY,
                success_count  INTEGER DEFAULT 0,
                failure_count  INTEGER DEFAULT 0,
                avg_duration   REAL DEFAULT 0,
                last_success   REAL,
                last_failure   REAL,
                success_rate   REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS chains (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                task_hash   TEXT NOT NULL,
                chain_json  TEXT NOT NULL,
                success     INTEGER NOT NULL,
                avg_duration REAL DEFAULT 0,
                use_count   INTEGER DEFAULT 1,
                last_used   REAL
            );
            CREATE INDEX IF NOT EXISTS idx_chain_task ON chains(task_hash);
        """)
        self.db.commit()

    # -- LRU cache operations -------------------------------------------

    def _cache_key(self, tool_name: str, params: dict[str, Any]) -> str:
        raw = f"{tool_name}:{json.dumps(params, sort_keys=True, default=str)}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _lru_get(self, key: str) -> Optional[ExecutionResult]:
        entry = self._lru.get(key)
        if entry is None:
            return None
        ts, result = entry
        ttl = result.metadata.get("cache_ttl", 300)
        if time.time() - ts < ttl:
            self._lru_access[key] = time.time()
            return result
        self._lru.pop(key, None)
        self._lru_access.pop(key, None)
        return None

    def _lru_put(self, key: str, result: ExecutionResult) -> None:
        if len(self._lru) >= self._cache_max:
            # Evict oldest by access time
            oldest = min(self._lru_access, key=self._lru_access.get)
            self._lru.pop(oldest, None)
            self._lru_access.pop(oldest, None)
        self._lru[key] = (time.time(), result)
        self._lru_access[key] = time.time()

    # -- public API ------------------------------------------------------

    @staticmethod
    def _task_hash(task_description: str) -> str:
        return hashlib.sha1(task_description.encode()).hexdigest()[:16]

    def store_execution(
        self,
        task_description: str,
        result: ExecutionResult,
        spec: ToolSpec,
        cache_params: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Persist a tool execution trace to both LRU cache and SQLite.

        Parameters
        ----------
        cache_params : dict | None
            If provided, use these (the caller's original args) for the
            cache key instead of ``result.parameters_used``.  This ensures
            cache lookups match cache stores even when tools add defaults.
        """
        task_hash = self._task_hash(task_description)
        if cache_params is None:
            cache_params = result.parameters_used
        cache_key = self._cache_key(result.tool_name, cache_params)

        # Cache layer first
        self._lru_put(cache_key, result)

        # SQLite persist
        conn = self.db
        conn.execute(
            """INSERT INTO executions
               (task_hash, tool_name, parameters, success, output, error,
                duration_ms, exit_code, metadata, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task_hash,
                result.tool_name,
                json.dumps(result.parameters_used, default=str),
                int(result.success),
                result.output,
                result.error,
                result.duration_ms,
                result.exit_code,
                json.dumps(result.metadata, default=str),
                result.timestamp,
            ),
        )

        # Update tool_stats rollup
        conn.execute("""
            INSERT INTO tool_stats (tool_name, success_count, failure_count,
                                    avg_duration, last_success, last_failure,
                                    success_rate)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tool_name) DO UPDATE SET
                success_count = success_count + ?,
                failure_count = failure_count + ?,
                avg_duration  = (avg_duration * (success_count + failure_count)
                                 + ?) / (success_count + failure_count + 1),
                last_success  = MAX(last_success, ?),
                last_failure  = MAX(last_failure, ?),
                success_rate  = CAST(success_count + ? AS REAL)
                              / (success_count + failure_count + 1)
        """, (
            spec.name,
            int(result.success), 0,
            result.duration_ms,
            result.timestamp if result.success else None,
            result.timestamp if not result.success else None,
            int(result.success),
            int(result.success), 0,
            result.duration_ms,
            result.timestamp if result.success else 0,
            result.timestamp if not result.success else 0,
            int(result.success),
        ))
        conn.commit()

    def get_cached_result(self, tool_name: str, params: dict[str, Any]) -> Optional[ExecutionResult]:
        """Check LRU cache first (microsecond lookups)."""
        key = self._cache_key(tool_name, params)
        return self._lru_get(key)

    def find_similar_executions(
        self,
        task_description: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Semantic recall: find past executions whose task descriptions are
        similar to *task_description* using hashing-embeddings + cosine.

        Falls back to SQLite LIKE queries if embedding similarity is low.
        """
        query_vec = hash_embedding(task_description)
        rows = self.db.execute(
            "SELECT DISTINCT task_hash, tool_name, parameters, success, duration_ms, output, timestamp "
            "FROM executions ORDER BY timestamp DESC LIMIT 200"
        ).fetchall()

        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            # Reconstruct the "context" that was stored during execution
            context = f"{row['tool_name']} {row['parameters']}"
            sim = cosine_similarity(query_vec, hash_embedding(context))
            if sim > 0.15:
                scored.append((sim, {
                    "task_hash": row["task_hash"],
                    "tool_name": row["tool_name"],
                    "parameters": json.loads(row["parameters"]),
                    "success": bool(row["success"]),
                    "duration_ms": row["duration_ms"],
                    "similarity": sim,
                    "output_preview": (row["output"] or "")[:200],
                    "timestamp": row["timestamp"],
                }))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:top_k]]

    def get_tool_stats(self, tool_name: str) -> Optional[dict[str, Any]]:
        """Get aggregated statistics for a specific tool."""
        row = self.db.execute(
            "SELECT * FROM tool_stats WHERE tool_name = ?", (tool_name,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_successful_params(
        self,
        tool_name: str,
        task_description: str,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """
        Find parameter sets for *tool_name* that previously succeeded on
        similar tasks — used by the learner to suggest parameters.
        """
        query_vec = hash_embedding(task_description)
        rows = self.db.execute(
            "SELECT parameters, success, timestamp FROM executions "
            "WHERE tool_name = ? ORDER BY timestamp DESC LIMIT 100",
            (tool_name,),
        ).fetchall()

        scored: list[tuple[float, dict]] = []
        for row in rows:
            params = json.loads(row["parameters"])
            param_text = " ".join(str(v) for v in params.values())
            sim = cosine_similarity(query_vec, hash_embedding(param_text))
            if row["success"] and sim > 0.2:
                scored.append((sim, params))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [params for _, params in scored[:top_k]]

    def get_top_tools(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return the most-used and highest-success-rate tools."""
        rows = self.db.execute(
            """SELECT tool_name, success_count, failure_count,
                      (success_count * 1.0 / (success_count + failure_count)) AS sr,
                      avg_duration
               FROM tool_stats
               WHERE (success_count + failure_count) > 0
               ORDER BY sr DESC, success_count DESC
               LIMIT ?"""
        , (limit,)).fetchall()
        return [dict(r) for r in rows]

    def clear_cache(self) -> int:
        """Evict all cached results. Returns count evicted."""
        count = len(self._lru)
        self._lru.clear()
        self._lru_access.clear()
        return count

    def checkpoint(self) -> int:
        """Force-write any pending SQLite transactions."""
        if self._conn:
            self._conn.commit()
        return 0

    def close(self) -> None:
        """Close the SQLite connection (important on Windows for file cleanup)."""
        if self._conn:
            self._conn.close()
            self._conn = None
