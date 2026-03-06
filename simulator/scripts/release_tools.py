#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import tomllib


SIM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SIM_ROOT.parent


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _pyproject_version() -> str:
    pyproject_path = SIM_ROOT / "pyproject.toml"
    data = tomllib.loads(_read_text(pyproject_path))
    return str(data["project"]["version"])


def _init_version() -> str:
    init_path = SIM_ROOT / "src" / "helpdesk_sim" / "__init__.py"
    match = re.search(r'__version__\s*=\s*"([^"]+)"', _read_text(init_path))
    if not match:
        raise RuntimeError("Unable to find __version__ in src/helpdesk_sim/__init__.py")
    return match.group(1)


def _main_version() -> str:
    main_path = SIM_ROOT / "src" / "helpdesk_sim" / "main.py"
    match = re.search(r'version\s*=\s*"([^"]+)"', _read_text(main_path))
    if not match:
        raise RuntimeError("Unable to find FastAPI version in src/helpdesk_sim/main.py")
    return match.group(1)


def _changelog_releases() -> list[tuple[str, str, str]]:
    changelog_path = REPO_ROOT / "CHANGELOG.md"
    content = _read_text(changelog_path)
    pattern = re.compile(r"^## \[([^\]]+)\](?: - ([0-9]{4}-[0-9]{2}-[0-9]{2}))?\s*$", re.MULTILINE)
    matches = list(pattern.finditer(content))
    releases: list[tuple[str, str, str]] = []
    for index, match in enumerate(matches):
        version = match.group(1).strip()
        if version.lower() == "unreleased":
            continue
        date = (match.group(2) or "").strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        body = content[start:end].strip()
        releases.append((version, date, body))
    return releases


def _latest_changelog_release() -> tuple[str, str, str]:
    releases = _changelog_releases()
    if not releases:
        raise RuntimeError("No release sections found in CHANGELOG.md")
    return releases[0]


def run_check() -> int:
    py_version = _pyproject_version()
    init_version = _init_version()
    main_version = _main_version()
    changelog_version, _date, _body = _latest_changelog_release()

    mismatches: list[str] = []
    if init_version != py_version:
        mismatches.append(
            f"Version mismatch: __init__.py has {init_version}, pyproject.toml has {py_version}"
        )
    if main_version != py_version:
        mismatches.append(
            f"Version mismatch: main.py has {main_version}, pyproject.toml has {py_version}"
        )
    if changelog_version != py_version:
        mismatches.append(
            f"Version mismatch: latest CHANGELOG section is {changelog_version}, expected {py_version}"
        )

    if mismatches:
        print("release-check: FAILED")
        for line in mismatches:
            print(f"- {line}")
        return 1

    print("release-check: OK")
    print(f"- pyproject.toml: {py_version}")
    print(f"- __init__.py: {init_version}")
    print(f"- main.py: {main_version}")
    print(f"- CHANGELOG latest heading: {changelog_version}")
    return 0


def run_notes(output_path: Path | None) -> int:
    version, date, body = _latest_changelog_release()
    title = f"## HD Simulation Software {version}"
    if date:
        title += f" ({date})"
    notes = f"{title}\n\n{body.strip()}\n"

    if output_path is not None:
        output_path.write_text(notes, encoding="utf-8")
        print(f"release-notes: wrote {output_path}")
    else:
        print(notes)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Release helpers for version sync checks and release-note drafting."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("check", help="Validate version sync across project files.")

    notes_parser = subparsers.add_parser("notes", help="Build release notes from latest changelog section.")
    notes_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output file path for generated release notes.",
    )

    args = parser.parse_args()
    if args.command == "check":
        return run_check()
    if args.command == "notes":
        return run_notes(args.output)
    return 1


if __name__ == "__main__":
    sys.exit(main())
