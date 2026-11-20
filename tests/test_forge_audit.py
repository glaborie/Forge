from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge_audit import AuditLog


def log_with(tmp_path: Path, count: int = 3) -> AuditLog:
    log = AuditLog(tmp_path / "audit.jsonl")
    for i in range(count):
        log.record(
            input_text=f"ignore previous instructions #{i}",
            policy="guardrail.input.v1",
            action="block",
            reason="prompt_injection",
            request_id=f"req-{i}",
            tenant_id="acme",
        )
    return log


def test_records_the_contracted_fields(tmp_path: Path) -> None:
    log = log_with(tmp_path, 1)
    entry = log.entries()[0]

    assert len(entry.input_hash) == 64
    assert entry.input_hash != "ignore previous instructions #0"  # never the raw text
    assert entry.policy == "guardrail.input.v1"
    assert entry.action == "block"
    assert entry.reason == "prompt_injection"
    assert entry.timestamp.endswith("Z") or "+00:00" in entry.timestamp
    assert entry.tenant_id == "acme"


def test_chain_verifies_and_detects_tampering(tmp_path: Path) -> None:
    log = log_with(tmp_path)
    log.verify()

    lines = log.path.read_text().splitlines()
    tampered = json.loads(lines[1])
    tampered["action"] = "allow"
    lines[1] = json.dumps(tampered, sort_keys=True)
    log.path.write_text("\n".join(lines) + "\n")

    with pytest.raises(ValueError, match="hash mismatch"):
        log.verify()


def test_deleting_a_record_breaks_the_chain(tmp_path: Path) -> None:
    log = log_with(tmp_path)
    lines = log.path.read_text().splitlines()
    log.path.write_text("\n".join([lines[0], lines[2]]) + "\n")

    with pytest.raises(ValueError, match="broken chain"):
        log.verify()


def test_appends_after_reopening_the_file(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    first = AuditLog(path)
    first.record(input_text="a", policy="p", action="allow", reason="ok")

    second = AuditLog(path)
    second.record(input_text="b", policy="p", action="block", reason="pii")

    entries = second.entries()
    assert [e.reason for e in entries] == ["ok", "pii"]
    assert entries[1].prev == entries[0].hash
    second.verify()


def test_exports_json_and_csv(tmp_path: Path) -> None:
    log = log_with(tmp_path, 2)

    as_json = json.loads(log.to_json())
    assert len(as_json) == 2
    assert as_json[0]["input_hash"] == log.entries()[0].input_hash

    csv_path = tmp_path / "audit.csv"
    log.to_csv(csv_path)
    rows = csv_path.read_text().strip().splitlines()
    assert rows[0].startswith("timestamp,input_hash,policy,action,reason")
    assert len(rows) == 3

    json_path = tmp_path / "export.json"
    log.to_json(json_path)
    assert len(json.loads(json_path.read_text())) == 2
