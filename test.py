"""
Run the test suite in the ``tests`` folder.

Usage:
    python test.py                # run every test in tests/
    python test.py -k ceda -x     # extra arguments are passed to pytest
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
TESTS_DIR = ROOT / "tests"


def main(argv: list[str] | None = None) -> int:
    """Run pytest on the tests folder and return its exit code."""
    extra = sys.argv[1:] if argv is None else argv
    # Put the repo root on sys.path so `clients` and the server modules import.
    sys.path.insert(0, str(ROOT))
    return int(pytest.main([str(TESTS_DIR), "-v", *extra]))


if __name__ == "__main__":
    sys.exit(main())
