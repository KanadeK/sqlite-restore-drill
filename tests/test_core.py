import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from sqlite_restore_drill import core


class DrillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "backup #百分%.sqlite"
        self.scratch = self.root / "scratch"
        self.scratch.mkdir()
        with closing(sqlite3.connect(self.source)) as connection:
            connection.executescript(
                "CREATE TABLE notes(id INTEGER PRIMARY KEY, body TEXT);"
                "INSERT INTO notes VALUES(1,'PRIVATE_ROW_VALUE'),(2,'Another value');"
                "PRAGMA user_version=2;"
            )

    def run_drill(self, **kwargs):
        return core.drill(self.source, temp_parent=self.scratch, **kwargs)

    @staticmethod
    def check(report, name):
        return next(check for check in report["checks"] if check["name"] == name)

    def test_full_offline_drill_preserves_every_source_byte(self):
        before = self.source.read_bytes()
        before_time = self.source.stat().st_mtime_ns
        report = self.run_drill(
            contract={
                "version": 1,
                "user_version": 2,
                "tables": {
                    "notes": {"min_rows": 2, "max_rows": 2, "required_columns": ["id", "body"]}
                },
            }
        )
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["input"]["sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(report["input"]["bytes"], len(before))
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(self.source.stat().st_mtime_ns, before_time)
        self.assertEqual(list(self.scratch.iterdir()), [])
        self.assertEqual(
            [c["name"] for c in report["checks"]],
            [
                "source",
                "integrity",
                "foreign_keys",
                "contract",
                "write_rollback",
                "source_unchanged",
            ],
        )
        self.assertNotIn("PRIVATE_ROW_VALUE", json.dumps(report))

    def test_sqlite_never_opens_original(self):
        connect = sqlite3.connect
        observed = []

        def guarded(path, *args, **kwargs):
            observed.append(Path(path))
            self.assertNotEqual(Path(path).resolve(), self.source.resolve())
            self.assertTrue(Path(path).is_relative_to(self.scratch))
            return connect(path, *args, **kwargs)

        with patch.object(core.sqlite3, "connect", side_effect=guarded):
            self.assertTrue(self.run_drill()["ok"])
        self.assertEqual(len(observed), 1)

    def test_rollback_smoke_leaves_schema_and_data_intact(self):
        with closing(sqlite3.connect(self.source)) as connection:
            schema = connection.execute("SELECT * FROM sqlite_schema").fetchall()
            rows = connection.execute("SELECT * FROM notes").fetchall()
            core._write_rollback(connection)
            self.assertEqual(connection.execute("SELECT * FROM sqlite_schema").fetchall(), schema)
            self.assertEqual(connection.execute("SELECT * FROM notes").fetchall(), rows)
            self.assertFalse(connection.in_transaction)

    def test_foreign_key_check_catches_what_integrity_check_does_not(self):
        with closing(sqlite3.connect(self.source)) as connection:
            connection.executescript(
                "CREATE TABLE parents(id INTEGER PRIMARY KEY);"
                "CREATE TABLE children(parent_id REFERENCES parents(id));"
                "INSERT INTO children VALUES(999);"
            )
        report = self.run_drill()
        self.assertFalse(report["ok"])
        self.assertTrue(self.check(report, "integrity")["ok"])
        self.assertEqual(self.check(report, "foreign_keys")["details"]["violation_count"], 1)

    def test_zero_byte_and_non_database_are_rejected(self):
        for payload in (b"", b"not sqlite" * 100):
            with self.subTest(size=len(payload)):
                self.source.write_bytes(payload)
                self.assertFalse(self.run_drill()["ok"])
                self.assertEqual(self.source.read_bytes(), payload)

    def test_truncated_database_is_rejected_and_scratch_cleaned(self):
        original = self.source.read_bytes()[:5000]
        self.source.write_bytes(original)
        report = self.run_drill()
        self.assertFalse(report["ok"])
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_missing_and_directory_input_are_reported(self):
        self.assertFalse(core.drill(self.root / "missing.sqlite")["ok"])
        self.assertFalse(core.drill(self.root)["ok"])

    def test_all_nonempty_sidecar_types_fail_closed(self):
        before = self.source.read_bytes()
        for suffix in ("-wal", "-journal", "-shm"):
            with self.subTest(suffix=suffix):
                sibling = Path(str(self.source) + suffix)
                sibling.write_bytes(b"sensitive unfinished transaction")
                report = self.run_drill()
                self.assertFalse(report["ok"])
                self.assertEqual(report["checks"][0]["details"]["code"], "sidecar_present")
                self.assertNotIn("sensitive", json.dumps(report))
                self.assertEqual(sibling.read_bytes(), b"sensitive unfinished transaction")
                sibling.unlink()
        self.assertEqual(before, self.source.read_bytes())

    def test_empty_regular_sidecar_is_allowed_and_not_removed(self):
        sibling = Path(str(self.source) + "-wal")
        sibling.touch()
        self.assertTrue(self.run_drill()["ok"])
        self.assertTrue(sibling.exists())

    def test_sidecar_directory_is_rejected(self):
        Path(str(self.source) + "-journal").mkdir()
        self.assertFalse(self.run_drill()["ok"])

    def test_real_live_wal_database_is_rejected_without_checkpoint(self):
        with closing(sqlite3.connect(self.source)) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("INSERT INTO notes VALUES(3,'Uncheckpointed value')")
            connection.commit()
            wal = Path(str(self.source) + "-wal")
            self.assertGreater(wal.stat().st_size, 0)
            before = self.source.read_bytes(), wal.read_bytes()
            self.assertFalse(self.run_drill()["ok"])
            self.assertEqual(before, (self.source.read_bytes(), wal.read_bytes()))

    def test_maximum_size_boundary(self):
        size = self.source.stat().st_size
        self.assertTrue(self.run_drill(max_bytes=size)["ok"])
        report = self.run_drill(max_bytes=size - 1)
        self.assertFalse(report["ok"])
        self.assertEqual(report["checks"][0]["details"]["code"], "size_limit")

    def test_tiny_budget_fails_instead_of_passing_partial_checks(self):
        report = self.run_drill(timeout=1e-15)
        self.assertFalse(report["ok"])
        self.assertEqual(report["checks"][0]["details"]["code"], "time_limit")

    def test_invalid_resource_options_raise(self):
        for value in (0, -1, float("nan"), float("inf"), True, "60"):
            with self.subTest(timeout=value), self.assertRaises(ValueError):
                self.run_drill(timeout=value)
        for value in (0, -1, 1.5, True):
            with self.subTest(max_bytes=value), self.assertRaises(ValueError):
                self.run_drill(max_bytes=value)

    def test_bad_temporary_directory_is_an_operational_failure(self):
        self.assertFalse(core.drill(self.source, temp_parent=self.root / "absent")["ok"])

    def test_source_changed_during_check_is_detected(self):
        check = core._check_contract

        def mutate(connection, contract):
            result = check(connection, contract)
            raw = self.source.read_bytes()
            self.source.write_bytes(raw + b"source changed")
            return result

        with patch.object(core, "_check_contract", side_effect=mutate):
            report = self.run_drill()
        self.assertFalse(report["ok"])
        self.assertFalse(self.check(report, "source_unchanged")["ok"])

    def test_sqlite_exception_text_is_not_exposed(self):
        with patch.object(
            core.sqlite3, "connect", side_effect=sqlite3.DatabaseError("PRIVATE_ROW_VALUE")
        ):
            report = self.run_drill()
        self.assertFalse(report["ok"])
        self.assertNotIn("PRIVATE_ROW_VALUE", json.dumps(report))
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_quoted_unicode_table_identifiers_are_safe(self):
        table = '筆記"; DROP TABLE notes;--'
        quoted = '"' + table.replace('"', '""') + '"'
        with closing(sqlite3.connect(self.source)) as connection:
            connection.execute("CREATE TABLE " + quoted + ' ("欄" INTEGER)')
            connection.execute("INSERT INTO " + quoted + " VALUES (1)")
            connection.commit()
        report = self.run_drill(
            contract={
                "version": 1,
                "tables": {
                    table: {"min_rows": 1, "required_columns": ["欄"]},
                    "notes": {"min_rows": 2},
                },
            }
        )
        self.assertTrue(report["ok"], report)

    def test_views_do_not_satisfy_required_tables(self):
        with closing(sqlite3.connect(self.source)) as connection:
            connection.execute("CREATE VIEW expected AS SELECT * FROM notes")
        report = self.run_drill(contract={"version": 1, "tables": {"expected": {}}})
        self.assertFalse(report["ok"])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO inputs exist on POSIX only")
    def test_fifo_input_is_rejected_without_opening_it(self):
        fifo = self.root / "pipe"
        os.mkfifo(fifo)
        self.assertFalse(core.drill(fifo)["ok"])


if __name__ == "__main__":
    unittest.main()
