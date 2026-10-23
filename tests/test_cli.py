"""Exercise the installed package from a clean user's working directory."""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from sqlite_restore_drill.core import drill

PRIVATE_ROW = "PRIVATE_ROW_CONTENT_6ed24e45024a"


def identifier(name):
    """Quote fixture identifiers; inputs are intentionally unusual."""
    return '"' + name.replace('"', '""') + '"'


class CliWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.cwd = self.root / "new-user-cwd"
        self.cwd.mkdir()
        self.database = self.root / "备份 #1 %& data.sqlite"
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
            connection.execute("INSERT INTO items(value) VALUES (?)", (PRIVATE_ROW,))
            connection.execute("PRAGMA user_version=7")
            connection.commit()
        self.original = self.database.read_bytes()

    def command(self, *args):
        environment = os.environ.copy()
        # Prevent the source tree from accidentally satisfying an uninstalled CLI.
        environment.pop("PYTHONPATH", None)
        environment["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [sys.executable, "-m", "sqlite_restore_drill", *map(str, args)],
            cwd=self.cwd,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )

    def write_contract(self, contract):
        path = self.root / "契约.json"
        path.write_text(json.dumps(contract, ensure_ascii=False), encoding="utf-8")
        return path

    def report(self, result, *, code, ok):
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["format_version"], 1)
        self.assertIs(report["ok"], ok)
        self.assertIsInstance(report["sqlite_version"], str)
        self.assertIsInstance(report["checks"], list)
        for check in report["checks"]:
            self.assertIsInstance(check["name"], str)
            self.assertIsInstance(check["ok"], bool)
        self.assertNotIn(PRIVATE_ROW, result.stdout + result.stderr)
        return report

    def assert_source_unchanged(self):
        self.assertEqual(self.database.read_bytes(), self.original)

    def test_full_workflow_checks_restore_and_does_not_rewrite_source(self):
        contract = self.write_contract(
            {
                "version": 1,
                "user_version": 7,
                "tables": {
                    "items": {"min_rows": 1, "max_rows": 1, "required_columns": ["id", "value"]}
                },
            }
        )
        scratch_parent = self.root / "scratch"
        scratch_parent.mkdir()
        report = self.report(
            self.command(
                self.database, "--contract", contract, "--json", "--temp-dir", scratch_parent
            ),
            code=0,
            ok=True,
        )
        checks = {check["name"]: check["ok"] for check in report["checks"]}
        for name in (
            "source",
            "integrity",
            "foreign_keys",
            "contract",
            "write_rollback",
            "source_unchanged",
        ):
            self.assertIs(checks.get(name), True, name)
        self.assertEqual(report["input"]["bytes"], len(self.original))
        self.assertEqual(report["input"]["sha256"], hashlib.sha256(self.original).hexdigest())
        self.assert_source_unchanged()
        self.assertEqual(
            list(scratch_parent.iterdir()), [], "Completed drills must remove their temporary copy"
        )

    def test_contract_failures_have_a_failing_check_and_nonzero_status(self):
        requirements = [
            {"version": 1, "tables": {"missing_table": {}}},
            {"version": 1, "tables": {"items": {"required_columns": ["missing_column"]}}},
            {"version": 1, "tables": {"items": {"min_rows": 2}}},
            {"version": 1, "tables": {"items": {"max_rows": 0}}},
            {"version": 1, "user_version": 8},
        ]
        for index, contract in enumerate(requirements):
            with self.subTest(case=index):
                report = self.report(
                    self.command(
                        self.database, "--contract", self.write_contract(contract), "--json"
                    ),
                    code=1,
                    ok=False,
                )
                self.assertTrue(
                    any(c["name"] == "contract" and not c["ok"] for c in report["checks"])
                )
                self.assert_source_unchanged()

    def test_no_contract_supports_a_complete_successful_drill(self):
        self.report(self.command(self.database, "--json"), code=0, ok=True)
        self.assert_source_unchanged()

    def test_special_sql_identifiers_work_without_interpreting_them_as_sql(self):
        table = '库存 "; DROP TABLE items; --'
        column = '列"名'
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute(f"CREATE TABLE {identifier(table)} ({identifier(column)} TEXT)")
            connection.execute(f"INSERT INTO {identifier(table)} VALUES (?)", (PRIVATE_ROW,))
            connection.commit()
        self.original = self.database.read_bytes()
        contract = self.write_contract(
            {
                "version": 1,
                "tables": {
                    table: {"min_rows": 1, "required_columns": [column]},
                    "items": {"min_rows": 1},
                },
            }
        )
        self.report(self.command(self.database, "--contract", contract, "--json"), code=0, ok=True)
        self.assert_source_unchanged()

    def test_foreign_key_failure_does_not_echo_the_bad_row(self):
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("CREATE TABLE parents (id TEXT PRIMARY KEY)")
            connection.execute("CREATE TABLE children (parent_id TEXT REFERENCES parents(id))")
            connection.execute("INSERT INTO children VALUES (?)", (PRIVATE_ROW,))
            connection.commit()
        self.original = self.database.read_bytes()
        report = self.report(self.command(self.database, "--json"), code=1, ok=False)
        self.assertTrue(any(c["name"] == "foreign_keys" and not c["ok"] for c in report["checks"]))
        self.assert_source_unchanged()

    def test_missing_source_fails_without_creating_a_database(self):
        missing = self.root / "does-not-exist.sqlite"
        self.report(self.command(missing, "--json"), code=1, ok=False)
        self.assertFalse(missing.exists())

    def test_source_limit_failure_preserves_source(self):
        self.report(self.command(self.database, "--max-bytes", "1", "--json"), code=1, ok=False)
        self.assert_source_unchanged()

    def test_bad_cli_numeric_arguments_are_usage_errors(self):
        invalid = [
            ("--timeout", "0"),
            ("--timeout", "-1"),
            ("--timeout", "nan"),
            ("--timeout", "inf"),
            ("--timeout", "not-a-number"),
            ("--max-bytes", "0"),
            ("--max-bytes", "-1"),
            ("--max-bytes", "1.5"),
        ]
        for args in invalid:
            with self.subTest(args=args):
                result = self.command(self.database, *args, "--json")
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertNotIn(PRIVATE_ROW, result.stdout + result.stderr)
        self.assert_source_unchanged()

    def test_invalid_contracts_are_usage_errors_and_do_not_leak_excerpts(self):
        secret = "PRIVATE_CONTRACT_INPUT_382d24ff"
        documents = [
            '{"version":1,"version":1}',
            '{"version":1,"user_version":' + "1" * 5000 + "}",
            '{"version":1,"options":"' + secret + '"}',
            '{"version":1,"tables":{"items":{"min_rows":"' + secret + '"}}}',
            '{"version":1,"tables":' + secret,
        ]
        path = self.root / "bad-contract.json"
        for index, document in enumerate(documents):
            with self.subTest(case=index):
                path.write_text(document, encoding="utf-8")
                result = self.command(self.database, "--contract", path, "--json")
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertNotIn(secret, result.stdout + result.stderr)
        self.assert_source_unchanged()

    def test_help_and_version_are_available_without_a_source(self):
        for option in ("--help", "--version"):
            with self.subTest(option=option):
                result = self.command(option)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(result.stdout.strip())


class DrillArgumentTests(unittest.TestCase):
    def test_api_rejects_invalid_limits_before_attempting_a_drill(self):
        invalid = [
            {"timeout": 0},
            {"timeout": -1},
            {"timeout": float("nan")},
            {"timeout": float("inf")},
            {"timeout": True},
            {"max_bytes": 0},
            {"max_bytes": -1},
            {"max_bytes": True},
            {"max_bytes": 1.5},
        ]
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "not-created.sqlite"
            for kwargs in invalid:
                with self.subTest(kwargs=kwargs):
                    with self.assertRaises(ValueError):
                        drill(missing, **kwargs)
            self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
