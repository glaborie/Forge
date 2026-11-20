"""Append-only audit log for guardrail decisions.

Each record is one JSON line on disk. Records are hash-chained: every entry
carries the hash of its predecessor, so deleting, reordering or editing a line
breaks `verify()`. That makes the log tamper-evident, which is what an auditor
can actually check; real tamper-proofing needs WORM storage, out of scope here.

Stdlib only — an audit trail should not depend on a library upgrading.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

Action = Literal["allow", "block", "redact", "flag", "log"]

GENESIS = "0" * 64


@dataclass(frozen=True)
class Entry:
    """One guardrail decision, as written to disk."""

    timestamp: str
    input_hash: str
    policy: str
    action: str
    reason: str
    request_id: str | None
    tenant_id: str | None
    prev: str
    hash: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Entry:
        return cls(
            timestamp=data["timestamp"],
            input_hash=data["input_hash"],
            policy=data["policy"],
            action=data["action"],
            reason=data["reason"],
            request_id=data.get("request_id"),
            tenant_id=data.get("tenant_id"),
            prev=data["prev"],
            hash=data["hash"],
        )


class AuditLog:
    """Append-only JSONL log. Safe to append from multiple threads."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._lock = threading.Lock()

    def record(
        self,
        *,
        input_text: str,
        policy: str,
        action: Action,
        reason: str,
        request_id: str | None = None,
        tenant_id: str | None = None,
        timestamp: str | None = None,
    ) -> Entry:
        """Append one decision. `input_text` is hashed, never stored."""
        with self._lock:
            prev = self._last_hash()
            entry = Entry(
                timestamp=timestamp or datetime.now(UTC).isoformat(timespec="milliseconds"),
                input_hash=hashlib.sha256(input_text.encode()).hexdigest(),
                policy=policy,
                action=action,
                reason=reason,
                request_id=request_id,
                tenant_id=tenant_id,
                prev=prev,
                hash="",
            )
            entry = Entry(**{**asdict(entry), "hash": _digest(asdict(entry))})
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(asdict(entry), sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return entry

    def entries(self) -> list[Entry]:
        return [
            Entry.from_dict(json.loads(line))
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def verify(self) -> None:
        """Raise ValueError if the chain is broken or a record was altered."""
        prev = GENESIS
        for number, entry in enumerate(self.entries(), start=1):
            if entry.prev != prev:
                raise ValueError(
                    f"record {number}: broken chain, prev={entry.prev!r} expected {prev!r}"
                )
            payload = {**asdict(entry), "hash": ""}
            if _digest(payload) != entry.hash:
                raise ValueError(f"record {number}: hash mismatch, the record was modified")
            prev = entry.hash

    def to_json(self, path: str | os.PathLike[str] | None = None) -> str:
        """Full export as a JSON array. Optionally written to `path`."""
        payload = json.dumps([asdict(entry) for entry in self.entries()], indent=2)
        if path is not None:
            Path(path).write_text(payload + "\n", encoding="utf-8")
        return payload

    def to_csv(self, path: str | os.PathLike[str]) -> None:
        fields = list(Entry.__dataclass_fields__)
        with Path(path).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for entry in self.entries():
                writer.writerow(asdict(entry))

    def _last_hash(self) -> str:
        if not self.path.stat().st_size:
            return GENESIS
        with self.path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            position = handle.tell()
            chunk = min(4096, position)
            handle.seek(position - chunk)
            last = handle.read().decode("utf-8").strip().splitlines()[-1]
        return json.loads(last)["hash"]


def _digest(record: dict[str, Any]) -> str:
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()
