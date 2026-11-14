from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from pathlib import Path

from .extract import extract_findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tarion-draft",
        description="Draft Tarion form entries from a home inspector PDF. Never submits anything.",
    )
    parser.add_argument("pdf", type=Path, help="Local path to the inspector report PDF")
    parser.add_argument("--output-dir", type=Path, default=Path("tarion-draft"))
    args = parser.parse_args(argv)

    items = extract_findings(args.pdf)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    (args.output_dir / "items.json").write_text(
        json.dumps([asdict(i) for i in items], indent=2), encoding="utf-8"
    )
    with (args.output_dir / "items.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["area", "page", "section", "title", "location", "task", "description", "reviewed"])
        for i in items:
            writer.writerow([i.area, i.page, i.section, i.title, i.location, i.task, i.description, ""])

    counts = {a: sum(1 for i in items if i.area == a) for a in ("exterior", "interior", "needs_review")}
    print(f"Wrote {len(items)} findings to {args.output_dir}: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
