#!/usr/bin/env python3
"""Single-process background worker for queued Thread Tree turns."""

from __future__ import annotations

import argparse
import json

from thread_tree_pipeline import process_all_pending, process_project


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id")
    parser.add_argument("--max-turns", type=int)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.project_id:
        result = process_project(args.project_id, max_turns=args.max_turns)
    else:
        result = process_all_pending(max_turns_per_project=args.max_turns)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
