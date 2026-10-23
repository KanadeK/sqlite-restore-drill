# Security policy

The latest tagged release is the supported version. Security fixes may require
an upgrade. Run on a supported Python release with current security patches.
The program makes no network requests and never collects telemetry.

Use GitHub's [private vulnerability reporting](https://github.com/KanadeK/sqlite-restore-drill/security/advisories/new)
to report a reproducible vulnerability. Include a synthetic reproducer, the
version and the impact. If private reporting is unavailable, open an issue
requesting a private contact channel **without disclosing the vulnerability**.
Do not publish tokens, private database files, test logs or personal data.

Input validation is a defense in depth measure, not a security sandbox.
The operating system, Python runtime and standard-library parsers remain
part of the trusted computing base. See the README for format-specific limits.
