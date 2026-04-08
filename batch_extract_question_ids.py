#!/usr/bin/env python3
"""
Split many question IDs into chunks (default 15), run prod (or beta) extract per chunk,
merge converted coding JSON into one array.

  NON_INTERACTIVE=1 DJANGO_TARGET_ENV=prod python3 batch_extract_question_ids.py ids.txt

ids.txt: one UUID per line, or a single JSON array of strings.

Outputs go to batch_extract_out/ and coding_questions_merged.json in the project root.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_ids(path: Path | None) -> list[str]:
    raw = path.read_text(encoding="utf-8").strip() if path else sys.stdin.read().strip()
    if not raw:
        raise SystemExit("No IDs: pass a file path or pipe stdin.")
    if raw.startswith("["):
        data = json.loads(raw)
        if not isinstance(data, list):
            raise SystemExit("JSON must be an array of question id strings.")
        return [str(x).strip() for x in data if str(x).strip()]
    return [ln.strip() for ln in raw.splitlines() if ln.strip() and not ln.strip().startswith("#")]


def chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch extract by question_ids (chunked).")
    parser.add_argument(
        "ids_file",
        nargs="?",
        help="File: one UUID per line, or JSON array. Omit to read stdin.",
    )
    parser.add_argument("--chunk-size", type=int, default=15, help="IDs per admin task (default 15).")
    parser.add_argument(
        "--out-dir",
        default="batch_extract_out",
        help="Directory for per-batch inputs/outputs (under project root).",
    )
    parser.add_argument(
        "--merge-out",
        default="coding_questions_merged.json",
        help="Merged JSON array path (project root).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print batch plan only; do not run extract.",
    )
    args = parser.parse_args()

    path = Path(args.ids_file) if args.ids_file else None
    ids = load_ids(path)
    batches = chunks(ids, max(1, args.chunk_size))

    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Total IDs: {len(ids)}  →  {len(batches)} batch(es) of up to {args.chunk_size}  (env: {os.environ.get('DJANGO_TARGET_ENV', 'beta')})")

    if args.dry_run:
        for i, b in enumerate(batches, start=1):
            print(f"  batch {i}: {len(b)} ids")
        return

    script = ROOT / "backend" / "scripts" / "run_extract_to_coding_json.sh"
    if not script.is_file():
        raise SystemExit(f"Missing {script}")

    env = {**os.environ, "NON_INTERACTIVE": "1", "PYTHONUNBUFFERED": "1"}
    if not env.get("DJANGO_TARGET_ENV"):
        env["DJANGO_TARGET_ENV"] = "prod"

    merged: list = []
    failed: list[int] = []

    for i, batch in enumerate(batches, start=1):
        stem = f"batch_{i:03d}"
        inp = out_dir / f"{stem}_input.json"
        raw_out = out_dir / f"{stem}_extracted.json"
        conv_out = out_dir / f"{stem}_coding.json"
        inp.write_text(json.dumps({"question_ids": batch}, indent=2), encoding="utf-8")
        print(f"\n>>> Batch {i}/{len(batches)} ({len(batch)} questions)…", flush=True)
        rc = subprocess.call(
            ["/bin/bash", str(script), str(inp), str(raw_out), str(conv_out)],
            cwd=str(ROOT),
            env=env,
        )
        if rc != 0:
            print(f"!!! Batch {i} failed (exit {rc})", flush=True)
            failed.append(i)
            continue
        try:
            data = json.loads(conv_out.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"!!! Batch {i} output unreadable: {e}", flush=True)
            failed.append(i)
            continue
        if isinstance(data, list):
            merged.extend(data)
            print(f"    Merged +{len(data)} question object(s); total {len(merged)}", flush=True)
        else:
            print(f"!!! Batch {i}: expected JSON array in {conv_out}", flush=True)
            failed.append(i)

    merge_path = ROOT / args.merge_out
    merge_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    print(f"\n>>> Wrote {merge_path} ({len(merged)} questions)")
    if failed:
        print(f"!!! Failed batches (re-run after fixing): {failed}")
        sys.exit(1)


if __name__ == "__main__":
    main()
