# Third-party components

No third-party source code, datasets or media are vendored. All runtime code
in this repository is newly implemented and uses the Python standard library.
Python and its bundled libraries retain their upstream licenses; they are
not redistributed in this source repository. Installation build tooling uses
setuptools. Optional developer tools are Ruff, coverage.py and PyPA build;
their upstream licenses apply to those separately installed packages.

The GitHub Actions workflow references actions/checkout and actions/setup-python
by verified upstream commit hashes. These actions run in GitHub's environment
and are not vendored here. Research links in the documentation are references,
not incorporated code.
