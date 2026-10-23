# Contributing

Report a reproducible problem with the Python version, the command, and a
minimal **synthetic** input. Never attach production data, credentials or logs
containing private content. Discuss behavior changes in an issue first.

```sh
python -m venv .venv
# POSIX: source .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m ruff check .
python -m ruff format --check .
python -m coverage run -m unittest discover -s tests -v
python -m coverage combine
python -m coverage report
python -m build
python scripts/installed_smoke.py
```

Keep core behavior local, deterministic and free of runtime dependencies.
Add regression coverage for input handling, byte/data preservation and CLI
exit behavior. Document supported input formats and failure modes.

This repository currently has one maintainer. CI checks and builds artifacts;
it never commits code. Third-party pull requests are reviewed before any
maintainer decision to incorporate them. Preserve upstream license notices
when proposing third-party material. See [SECURITY.md](SECURITY.md) for
private vulnerability reports.
