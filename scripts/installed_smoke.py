"""Exercise a fresh offline wheel install from outside the checkout."""

import hashlib
import json
import os
import subprocess
import tempfile
import venv
from pathlib import Path


def main():
    project = Path(__file__).resolve().parents[1]
    wheels = list((project / "dist").glob("*.whl"))
    if len(wheels) != 1:
        raise RuntimeError("Build exactly one wheel first: python -m build")
    with tempfile.TemporaryDirectory(prefix="restore-drill-install-") as work:
        root = Path(work)
        venv.EnvBuilder(with_pip=True).create(root / "venv")
        binary = root / "venv" / ("Scripts" if os.name == "nt" else "bin")
        python = binary / ("python.exe" if os.name == "nt" else "python")
        command = binary / (
            "sqlite-restore-drill.exe" if os.name == "nt" else "sqlite-restore-drill"
        )

        def run(*args, expected=0):
            result = subprocess.run(
                [str(a) for a in args],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )
            if result.returncode != expected:
                raise RuntimeError(f"Smoke command failed ({result.returncode}): {result.stderr}")
            return result

        run(python, "-m", "pip", "install", "--no-index", "--no-deps", wheels[0])
        database = root / "demo.db"
        run(python, project / "examples" / "make_demo.py", database)
        before = hashlib.sha256(database.read_bytes()).digest()
        report = json.loads(
            run(
                command, database, "--contract", project / "examples" / "contract.json", "--json"
            ).stdout
        )
        assert report["ok"] and len(report["checks"]) == 6
        assert hashlib.sha256(database.read_bytes()).digest() == before
        bad_contract = root / "too-many.json"
        bad_contract.write_text('{"version":1,"tables":{"notes":{"min_rows":3}}}', encoding="utf-8")
        failed = json.loads(
            run(command, database, "--contract", bad_contract, "--json", expected=1).stdout
        )
        assert not failed["ok"]
        run(python, "-m", "sqlite_restore_drill", "--version")
        run(python, "-m", "pip", "uninstall", "-y", "sqlite-restore-drill")
    print("Fresh offline wheel install, successful/failing user workflows and uninstall passed.")


if __name__ == "__main__":
    main()
