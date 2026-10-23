"""Command-line interface with data-free operational diagnostics."""

import argparse
import json
import math

from . import __version__
from .core import DEFAULT_MAX_BYTES, ContractError, drill, load_contract


def _positive_int(text):
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("expected a positive integer") from None
    if value <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return value


def _positive_float(text):
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError("expected a finite positive number") from None
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("expected a finite positive number")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Rehearse a closed, single-file SQLite backup in a disposable directory."
    )
    parser.add_argument("source", help="offline SQLite backup file (not a live database)")
    parser.add_argument("--contract", help="version-1 JSON table/column/row-count contract")
    parser.add_argument("--json", action="store_true", help="emit a machine-readable report")
    parser.add_argument(
        "--timeout",
        type=_positive_float,
        default=60.0,
        help="cooperative time budget in seconds (default: 60)",
    )
    parser.add_argument(
        "--max-bytes",
        type=_positive_int,
        default=DEFAULT_MAX_BYTES,
        help="maximum input bytes (default: 1 GiB)",
    )
    parser.add_argument("--temp-dir", help="existing parent directory for the disposable copy")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    try:
        contract = load_contract(args.contract) if args.contract else None
    except ContractError as exc:
        parser.error(str(exc))
    report = drill(
        args.source,
        contract=contract,
        timeout=args.timeout,
        max_bytes=args.max_bytes,
        temp_parent=args.temp_dir,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    else:
        print("PASS" if report["ok"] else "FAIL")
        for check in report["checks"]:
            print(f"  {'ok' if check['ok'] else 'FAIL'}: {check['name']}")
        if report["input"]:
            print("  input SHA-256: " + report["input"]["sha256"])
        if not report["ok"]:
            print("Use --json for reason codes and aggregate check details.")
    return 0 if report["ok"] else 1
