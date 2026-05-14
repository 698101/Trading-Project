#!/usr/bin/env python3
"""Move broken quote artifacts out of active quote directories without deleting them."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import shutil
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quote-dir", required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--quarantine-dir", default="build/quote_quarantine")
    parser.add_argument("--move-temp", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--move-non-ok", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def unique_destination(base_dir: Path, source: Path) -> Path:
    destination = base_dir / source.name
    if not destination.exists():
        return destination
    stem = source.stem
    suffix = source.suffix
    counter = 1
    while True:
        candidate = base_dir / f"{stem}.{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def non_ok_paths(manifest: Path) -> list[Path]:
    if not manifest:
        return []
    paths: list[Path] = []
    with manifest.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row["status"].strip() != "ok":
                paths.append(Path(row["file_path"]))
    return paths


def move_files(paths: list[Path], quarantine_dir: Path, dry_run: bool) -> int:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination_dir = quarantine_dir / stamp
    moved = 0
    for path in paths:
        if not path.exists():
            continue
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = unique_destination(destination_dir, path)
        print(f"quarantine source={path} destination={destination}", flush=True)
        if not dry_run:
            shutil.move(str(path), str(destination))
        moved += 1
    return moved


def main() -> int:
    args = parse_args()
    quote_dir = Path(args.quote_dir)
    paths: list[Path] = []
    if args.move_temp:
        paths.extend(sorted(quote_dir.glob("*.tmp")))
    if args.move_non_ok:
        if not args.manifest:
            raise SystemExit("--manifest is required with --move-non-ok")
        paths.extend(non_ok_paths(Path(args.manifest)))

    unique_paths = []
    seen = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique_paths.append(path)

    moved = move_files(unique_paths, Path(args.quarantine_dir), args.dry_run)
    print(f"quarantined={moved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
