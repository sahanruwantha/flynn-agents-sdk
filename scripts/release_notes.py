"""Validate a release tag and emit its changelog entry. No network or mutations."""

import argparse
import re
import tomllib
from pathlib import Path


def release_notes(root: Path, tag: str) -> str:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version) or tag != f"v{version}":
        raise ValueError(f"Tag {tag!r} must match the project version v{version}")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(
        rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}\n(.*?)(?=^## |^\[|\Z)",
        changelog,
        re.MULTILINE | re.DOTALL,
    )
    if not match or not match[1].strip():
        raise ValueError(f"Missing dated changelog entry for {version}")
    return match[1].strip() + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    args = parser.parse_args()
    try:
        print(release_notes(Path(__file__).resolve().parents[1], args.tag), end="")
    except ValueError as error:
        parser.exit(1, f"Release validation failed: {error}\n")
