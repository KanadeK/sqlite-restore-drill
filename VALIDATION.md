# Validation scope for v0.1.0

Local validation used Windows, Python 3.13.16 and SQLite 3.50.4.

- 41 unittest methods: 40 passed, one POSIX-only FIFO check skipped on Windows.
- Coverage.py measured 90% combined statement/branch coverage, including CLI subprocesses.
- Ruff checks and formatting checks passed.
- A wheel and source distribution were built successfully.
- A fresh virtual environment installed the wheel with `--no-index --no-deps`,
  exercised successful and failing contract workflows, verified source hashes
  and uninstalled the package successfully.
- An independent review added contract/CLI regressions and verified fixed
  Windows stat/fstat differences and oversized-number error handling.
- Runtime dependency review: no third-party runtime packages. An empty-runtime
  requirements audit found no package advisories; this does not audit Python,
  SQLite, developer tooling or the operating system.

The checked-in CI tests Ubuntu with Python 3.11 and 3.13, plus Windows and macOS
with Python 3.13. Consult the actual Actions run for platform results; the local
run above does not claim those systems were available on the development host.
Coverage is a regression signal, not proof of correctness or security.

Run the commands in CONTRIBUTING.md to reproduce. See README.md for the limits
of a passing backup drill.
