# v0.1.0

Initial release of the offline, single-file SQLite restore drill.

- Copy the source as bytes; open only the disposable restore with SQLite.
- Run full integrity and foreign-key checks.
- Validate strict JSON contracts for tables, required columns, row bounds and user_version.
- Exercise create/insert/read/rollback and check source fingerprints afterward.
- Reject unsafe sidecar states; bound input size and use a cooperative time budget.
- Provide privacy-conscious JSON reports, working synthetic examples, unit/integration/CLI tests and cross-platform CI.

Limitations: closed ordinary SQLite backup files only; no live WAL sets, dumps,
encryption, remote stores, application recovery guarantee or hard process timeout.
See the README for exact behavior and alternatives.
