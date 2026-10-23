"""Rehearse a closed, single-file SQLite backup without SQLite-opening its source."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import stat
import tempfile
import time
import uuid
from contextlib import closing
from pathlib import Path

DEFAULT_MAX_BYTES = 1024 * 1024 * 1024
_CHUNK = 1024 * 1024
_HEADER = b"SQLite format 3\x00"


class ContractError(ValueError):
    """A contract is invalid. Messages intentionally exclude input values."""


class _DrillFailure(Exception):
    pass


class _TimeLimit(_DrillFailure):
    pass


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("Duplicate JSON object key in contract")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ContractError("Non-finite JSON value in contract")


def _integer(value, message):
    if type(value) is not int or value < 0:
        raise ContractError(message)


def _identifier(value):
    if not isinstance(value, str) or not 0 < len(value) <= 1024 or "\x00" in value:
        return False
    try:
        value.encode("utf-8")
    except UnicodeError:
        return False
    return True


def validate_contract(contract: dict | None) -> dict:
    """Validate an explicit version-1 contract; no free-form SQL is accepted."""
    if contract is None:
        return {"version": 1, "tables": {}}
    if not isinstance(contract, dict) or set(contract) - {"version", "user_version", "tables"}:
        raise ContractError("Contract must be an object with supported keys only")
    if type(contract.get("version")) is not int or contract["version"] != 1:
        raise ContractError("Contract version must be 1")
    if "user_version" in contract:
        _integer(contract["user_version"], "user_version must be a non-negative integer")
        if contract["user_version"] > 2147483647:
            raise ContractError("user_version exceeds SQLite's signed 32-bit range")
    tables = contract.get("tables", {})
    if not isinstance(tables, dict) or len(tables) > 1000:
        raise ContractError("tables must be an object with at most 1000 entries")
    for name, rule in tables.items():
        if not _identifier(name):
            raise ContractError("Invalid table identifier in contract")
        if not isinstance(rule, dict) or set(rule) - {"min_rows", "max_rows", "required_columns"}:
            raise ContractError("Table rule must be an object with supported keys only")
        for bound in ("min_rows", "max_rows"):
            if bound in rule:
                _integer(rule[bound], "Row bounds must be non-negative integers")
        if rule.get("min_rows", 0) > rule.get("max_rows", math.inf):
            raise ContractError("min_rows must not exceed max_rows")
        columns = rule.get("required_columns", [])
        if not isinstance(columns, list) or len(columns) > 1000:
            raise ContractError("required_columns must be a list with at most 1000 entries")
        if any(not _identifier(column) for column in columns) or len(set(columns)) != len(columns):
            raise ContractError("Required columns must be valid, unique identifiers")
    # Return a detached snapshot so caller mutation cannot change a running drill.
    return json.loads(json.dumps(contract))


def load_contract(path: str | Path) -> dict:
    """Load a bounded UTF-8 JSON contract, rejecting duplicate and unknown keys."""
    try:
        with Path(path).open("rb") as handle:
            raw = handle.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ContractError("Contract exceeds 1 MiB")
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
        # A file containing null is not an omitted contract.
        if value is None:
            raise ContractError("Contract file must contain an object")
        return validate_contract(value)
    except ContractError:
        raise
    except (OSError, ValueError, RecursionError) as exc:
        raise ContractError("Cannot read a valid UTF-8 JSON contract") from exc


def _signature(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _sidecars(path):
    """Reject nonempty, linked or unusual sidecars, including dangling links."""
    for suffix in ("-wal", "-journal", "-shm"):
        sibling = Path(str(path) + suffix)
        if os.path.lexists(sibling):
            info = sibling.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_size:
                raise _DrillFailure("sidecar_present")


def _quoted(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _check_contract(connection, contract):
    issues = []
    if "user_version" in contract:
        actual = connection.execute("PRAGMA user_version").fetchone()[0]
        if actual != contract["user_version"]:
            issues.append(
                {"rule": "user_version", "expected": contract["user_version"], "actual": actual}
            )
    for table, rules in contract.get("tables", {}).items():
        row = connection.execute(
            "SELECT type, sql FROM sqlite_schema WHERE name = ? COLLATE BINARY", (table,)
        ).fetchone()
        if row is None or row[0] != "table":
            issues.append({"rule": "missing_table", "table": table})
            continue
        # Virtual tables can invoke extensions and may have unrelated backing data.
        if row[1] and row[1].lstrip().upper().startswith("CREATE VIRTUAL TABLE"):
            issues.append({"rule": "virtual_table_unsupported", "table": table})
            continue
        if "required_columns" in rules:
            columns = {
                column[1]
                for column in connection.execute("PRAGMA table_xinfo(" + _quoted(table) + ")")
            }
            missing = [c for c in rules["required_columns"] if c not in columns]
            if missing:
                issues.append({"rule": "missing_columns", "table": table, "count": len(missing)})
        if "min_rows" in rules or "max_rows" in rules:
            count = connection.execute("SELECT count(*) FROM " + _quoted(table)).fetchone()[0]
            if count < rules.get("min_rows", 0) or count > rules.get("max_rows", math.inf):
                issues.append(
                    {
                        "rule": "row_count",
                        "table": table,
                        "actual": count,
                        **{key: rules[key] for key in ("min_rows", "max_rows") if key in rules},
                    }
                )
    return issues


def _write_rollback(connection):
    name = "_restore_drill_" + uuid.uuid4().hex
    quoted = _quoted(name)
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute("CREATE TABLE " + quoted + " (value INTEGER NOT NULL)")
        connection.execute("INSERT INTO " + quoted + " VALUES (7)")
        if connection.execute("SELECT value FROM " + quoted).fetchone() != (7,):
            raise _DrillFailure("write_readback_failed")
    finally:
        connection.rollback()
    if connection.execute("SELECT 1 FROM sqlite_schema WHERE name = ?", (name,)).fetchone():
        raise _DrillFailure("rollback_failed")


def drill(
    source: str | Path,
    *,
    contract: dict | None = None,
    timeout: float = 60.0,
    max_bytes: int = DEFAULT_MAX_BYTES,
    temp_parent: str | Path | None = None,
) -> dict:
    """Run checks on a private byte copy. Operational failures return an unsuccessful report.

    The caller must provide a closed, self-contained backup. Before/after hashes
    detect ordinary concurrent changes; they are not a filesystem lock or proof
    that a file copied from a running database was consistent.
    """
    contract = validate_contract(contract)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise ValueError("timeout must be a finite positive number")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a finite positive number")
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    deadline = time.monotonic() + timeout

    def budget():
        if time.monotonic() >= deadline:
            raise _TimeLimit("time_limit")

    def progress():
        return int(time.monotonic() >= deadline)

    def digest(path):
        result = hashlib.sha256()
        total = 0
        with path.open("rb") as stream:
            while chunk := stream.read(_CHUNK):
                budget()
                total += len(chunk)
                if total > max_bytes:
                    raise _DrillFailure("size_limit")
                result.update(chunk)
        return total, result.hexdigest()

    report = {
        "format_version": 1,
        "ok": False,
        "sqlite_version": sqlite3.sqlite_version,
        "input": None,
        "checks": [],
    }

    def add(name, ok, **details):
        report["checks"].append({"name": name, "ok": ok, "details": details})

    stage = "source"
    try:
        path = Path(source).resolve(strict=True)
        budget()
        path_before = path.stat()
        if not stat.S_ISREG(path_before.st_mode):
            raise _DrillFailure("not_regular_file")
        _sidecars(path)
        with path.open("rb") as original:
            before = os.fstat(original.fileno())
            if (before.st_dev, before.st_ino) != (path_before.st_dev, path_before.st_ino):
                raise _DrillFailure("source_changed")
            if not stat.S_ISREG(before.st_mode):
                raise _DrillFailure("not_regular_file")
            if before.st_size > max_bytes:
                raise _DrillFailure("size_limit")
            if before.st_size < 100 or original.read(16) != _HEADER:
                raise _DrillFailure("invalid_sqlite_header")
            original.seek(0)
            with tempfile.TemporaryDirectory(
                prefix="sqlite-restore-drill-", dir=temp_parent
            ) as work:
                copy = Path(work) / "restored.sqlite"
                fingerprint = hashlib.sha256()
                copied = 0
                with copy.open("xb") as target:
                    while chunk := original.read(_CHUNK):
                        budget()
                        copied += len(chunk)
                        if copied > max_bytes:
                            raise _DrillFailure("size_limit")
                        target.write(chunk)
                        fingerprint.update(chunk)
                if _signature(os.fstat(original.fileno())) != _signature(before):
                    raise _DrillFailure("source_changed")
                _sidecars(path)
                report["input"] = {"bytes": copied, "sha256": fingerprint.hexdigest()}
                add("source", True, code="offline_copy", bytes=copied)
                budget()
                stage = "integrity"
                with closing(sqlite3.connect(copy, timeout=min(timeout, 0.25))) as connection:
                    connection.set_progress_handler(progress, 1000)
                    connection.execute("PRAGMA trusted_schema=OFF")
                    stage = "integrity"
                    integrity_errors = 0
                    integrity_rows = 0
                    # Never expose SQLite's potentially data-bearing diagnostic strings.
                    for row in connection.execute("PRAGMA integrity_check"):
                        budget()
                        integrity_rows += 1
                        if row != ("ok",):
                            integrity_errors += 1
                    add(
                        stage,
                        integrity_errors == 0 and integrity_rows == 1,
                        error_count=integrity_errors,
                        result_count=integrity_rows,
                    )
                    stage = "foreign_keys"
                    connection.execute("PRAGMA foreign_keys=ON")
                    if connection.execute("PRAGMA foreign_keys").fetchone() != (1,):
                        raise _DrillFailure("foreign_keys_unavailable")
                    foreign_errors = 0
                    for _row in connection.execute("PRAGMA foreign_key_check"):
                        budget()
                        foreign_errors += 1
                    add(stage, foreign_errors == 0, violation_count=foreign_errors)
                    stage = "contract"
                    issues = _check_contract(connection, contract)
                    add(
                        stage,
                        not issues,
                        issues=issues,
                        tables_checked=len(contract.get("tables", {})),
                    )
                    stage = "write_rollback"
                    budget()
                    _write_rollback(connection)
                    add(stage, True, code="create_insert_read_rollback")
                stage = "source_unchanged"
                after_size, after_hash = digest(path)
                _sidecars(path)
                # Windows can expose different ctime values through stat and fstat.
                # Compare each API to its own baseline, retaining replacement detection.
                unchanged = (
                    _signature(path.stat()) == _signature(path_before)
                    and _signature(os.fstat(original.fileno())) == _signature(before)
                    and after_size == copied
                    and after_hash == fingerprint.hexdigest()
                )
                add(stage, unchanged, code="matched" if unchanged else "source_changed")
        report["ok"] = all(check["ok"] for check in report["checks"])
    except _DrillFailure as exc:
        add(stage, False, code=str(exc))
    except sqlite3.Error:
        code = "time_limit" if time.monotonic() >= deadline else "sqlite_error"
        add(stage, False, code=code)
    except (OSError, ValueError):
        add(stage, False, code="filesystem_error")
    return report
