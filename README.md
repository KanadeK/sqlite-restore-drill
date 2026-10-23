# sqlite-restore-drill

Rehearse a **closed, single-file SQLite backup** before you need it: validate its
structure, foreign keys, expected tables, columns and row counts, then prove a
disposable restore can write and roll back a transaction.

[中文说明](README.zh-CN.md) · [MIT license](LICENSE) · Python 3.11+ · No runtime dependencies

The original is read as bytes and is **never opened by SQLite**. Every SQLite
operation runs on a private temporary copy, which is removed when the command
finishes. No server, external `sqlite3` executable, account or network is required.

## Install

```sh
git clone https://github.com/KanadeK/sqlite-restore-drill.git
cd sqlite-restore-drill
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
python -m pip install .
```

You can also download the wheel from the GitHub release and run
`python -m pip install --no-deps path/to/sqlite_restore_drill-0.1.0-py3-none-any.whl`.
No PyPI publication is implied. The source installation may download setuptools
as build tooling; the installed command itself is offline.

## Try the complete workflow

```sh
python examples/make_demo.py demo.db
sqlite-restore-drill demo.db --contract examples/contract.json
sqlite-restore-drill demo.db --contract examples/contract.json --json
```

The generator creates two clearly synthetic notes and closes the database.
The text report starts with `PASS`; the JSON report has `"ok": true`. To see a
meaningful failure, change `min_rows` in a copy of the example contract to `3`:
the contract check fails while structural integrity still passes.

For your own data, first create a consistent backup using your application's
documented backup procedure or SQLite's
[Online Backup API](https://www.sqlite.org/backup.html), then stop all writers to
that **backup file** before running:

```sh
sqlite-restore-drill backup.sqlite --contract restore-contract.json --json
```

Do not copy a live database using an ordinary filesystem copy and assume this
tool can recover omitted transactions. Nonempty `-wal`, `-journal` and `-shm`
siblings are rejected, as are linked or nonregular sidecars. Empty regular
sidecars are tolerated and left untouched. Missing sidecars do not prove a
backup was created consistently.

## Data contract

```json
{
  "version": 1,
  "user_version": 2,
  "tables": {
    "notes": {
      "min_rows": 2,
      "max_rows": 100,
      "required_columns": ["id", "body"]
    }
  }
}
```

`version` is required; the other fields are optional. Table and column names are
matched exactly, including case. Each listed object must be a real table, not a
view. Row bounds are inclusive, non-negative integers; `min_rows` cannot exceed
`max_rows`. Booleans, unknown fields, duplicate JSON keys, nonfinite values,
duplicate required columns and invalid identifiers are rejected. `user_version`
is a non-negative signed 32-bit integer. Contracts are limited to 1 MiB and 1000
tables/columns per rule. Free-form SQL is deliberately outside the format.

Without a contract the command checks structure, foreign keys and the basic
write/rollback workflow. It cannot know whether the backup contains the tables
or data you intended; a correctly formatted empty-schema database can pass.

## Checks and automation

| Check | What it establishes |
| --- | --- |
| `source` | Valid SQLite header, size limit, sidecar policy and byte copy |
| `integrity` | SQLite's full `PRAGMA integrity_check` reports no problems |
| `foreign_keys` | `PRAGMA foreign_key_check` returns no violations |
| `contract` | Required real tables/columns, row bounds and `user_version` match |
| `write_rollback` | Create a private test table, insert/read one value, roll back, verify removal |
| `source_unchanged` | Source size, identity/timestamps and SHA-256 match after the drill |

SQLite's [integrity check does not check foreign keys](https://www.sqlite.org/pragma.html#pragma_integrity_check),
so both checks are always run. A failed check never produces a successful exit.
Severe corruption can stop later checks; the report lists the checks actually run.

| Exit | Meaning |
| --- | --- |
| `0` | Every attempted drill check passed, including source verification |
| `1` | Drill failed, including missing/invalid input, sidecar, resource or filesystem failure |
| `2` | Invalid arguments or contract |

`--json` produces a versioned report with `format_version`, `ok`, the SQLite
runtime version, input byte count/SHA-256 and check results. Operational errors
use fixed reason codes; database rows and SQLite error text are never printed.
Contract diagnostics can include **schema table names**, expected/actual counts
and versions. Treat reports as potentially private metadata. Argument and
contract errors are plain stderr, including with `--json`.

`--max-bytes N` defaults to 1 GiB. The temporary disk needs roughly the backup's
size plus SQLite working/journal space. `--temp-dir DIR` selects an existing
parent directory. `--timeout SECONDS` defaults to 60 and is a cooperative budget
checked during copying, hashing and SQLite execution. It cannot interrupt a
blocked filesystem call and is not a hard process deadline. Use your job runner's
process timeout when a hard deadline is required. `python -m sqlite_restore_drill`
is equivalent to the installed command.

## Limits and alternatives

v0.1.0 supports ordinary, unencrypted, self-contained SQLite files. It does not
restore live WAL sets, SQL dumps, remote backups or encrypted databases. Virtual
tables are not supported by contracts; databases needing unavailable extensions
can fail. SQLite runtime behavior also matters: older engines can report issues
for valid contentless FTS4 tables. Use a current Python/SQLite build and consult
the engine's release notes when investigating such a failure.

A passing drill is **not proof of freshness, application correctness, complete
business data or application-specific write compatibility**. The write smoke
test uses its own temporary table. Hashes detect ordinary changes; they do not
lock the source or authenticate its origin. The private copy is a disposable
workspace, not a security sandbox for hostile database files. Keep Python and
SQLite patched. An abruptly killed process can leave OS temporary files; inspect
and remove only this tool's `sqlite-restore-drill-*` directories after confirming
the process has stopped.

[RestoreVerify](https://github.com/RestoreVerify/restoreverify) already supports
local SQLite verification and broader database workflows.
[Probavi](https://github.com/probavi/probavi) offers recovery verification with
row checks, providers and signed evidence; its SQLite adapter also fences
sidecars. [sqlite-vault](https://github.com/suhlig/sqlite-vault) verifies its
encrypted S3 backup workflow. Choose them for those broader needs. This project
offers a small, standalone Python workflow with built-in foreign-key checks,
explicit column/version contracts and an actual rollback write drill.

## Development and cleanup

See [CONTRIBUTING.md](CONTRIBUTING.md) for tests, static checks, build and fresh
wheel-install smoke tests. CI tests Linux, Windows and macOS and never commits
code. [SECURITY.md](SECURITY.md) describes private reporting.

Uninstall with `python -m pip uninstall sqlite-restore-drill`. Delete the virtual
environment and generated `demo.db` when no longer needed. Normal runs remove
their temporary copy and create no persistent state or telemetry.
