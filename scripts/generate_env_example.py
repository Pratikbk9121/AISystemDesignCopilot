"""
Regenerate or check `.env.example` against the field set declared by
`app.core.config.Settings`.

Usage:
    python scripts/generate_env_example.py            # rewrite .env.example
    python scripts/generate_env_example.py --check    # exit 1 if any aliased
                                                      # field is missing from
                                                      # .env.example (CI / pre-commit)

Notes:
- Only Pydantic fields with an explicit `alias=` (i.e. those the user is
  expected to set via env var) are tracked. Pure code-side defaults
  (`app_name`, `app_version`, internal toggles without an alias) are not
  required to appear in `.env.example`.
- The script does not overwrite ordering or comments when `--check` is used;
  it only verifies presence.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = REPO_ROOT / ".env.example"


def _collect_aliased_env_keys() -> set[str]:
    sys.path.insert(0, str(REPO_ROOT))
    from app.core.config import Settings  # noqa: WPS433

    keys: set[str] = set()
    for _name, field in Settings.model_fields.items():
        if field.alias:
            keys.add(field.alias.upper())
    return keys


def _keys_in_env_example() -> set[str]:
    if not ENV_EXAMPLE.exists():
        return set()
    keys: set[str] = set()
    for raw in ENV_EXAMPLE.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        keys.add(line.split("=", 1)[0].strip().upper())
    return keys


def check() -> int:
    expected = _collect_aliased_env_keys()
    present = _keys_in_env_example()
    missing = sorted(expected - present)
    if missing:
        sys.stderr.write(
            ".env.example is missing keys declared in Settings:\n  - "
            + "\n  - ".join(missing)
            + "\nRun `python scripts/generate_env_example.py` to update.\n"
        )
        return 1
    return 0


def regenerate() -> int:
    # Intentionally minimal: we don't auto-overwrite the curated .env.example
    # because it carries explanatory comments. Instead, print the gap so the
    # author can fill it in by hand.
    expected = _collect_aliased_env_keys()
    present = _keys_in_env_example()
    missing = sorted(expected - present)
    extra = sorted(present - expected)
    if not missing and not extra:
        print(".env.example is in sync with Settings.")
        return 0
    if missing:
        print("Add to .env.example:")
        for key in missing:
            print(f"  {key}=")
    if extra:
        print("Keys present in .env.example but not in Settings (probably stale):")
        for key in extra:
            print(f"  {key}")
    return 1 if missing else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    return check() if args.check else regenerate()


if __name__ == "__main__":
    raise SystemExit(main())
