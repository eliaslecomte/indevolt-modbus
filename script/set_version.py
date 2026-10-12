"""Set a validated release version in pyproject.toml."""

import re
import sys
from pathlib import Path


def main() -> None:
    """Accept only an explicit semantic release tag, then replace the placeholder."""
    if len(sys.argv) != 2 or not re.fullmatch(
        r"\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?", sys.argv[1]
    ):
        raise SystemExit("Expected a bare release version, for example 0.1.0")
    path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    source = path.read_text()
    old = 'version = "0.0.0"'
    if source.count(old) != 1:
        raise SystemExit("Expected exactly one development version placeholder")
    path.write_text(source.replace(old, f'version = "{sys.argv[1]}"'))


if __name__ == "__main__":
    main()
