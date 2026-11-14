from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .explorer import crawl


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Read-only Horizon authenticated-session explorer.")
    result.add_argument("--cdp-url", required=True, help="Local CDP endpoint, e.g. http://127.0.0.1:9222")
    result.add_argument("--start-url", required=True)
    result.add_argument("--output-dir", type=Path, default=Path("evidence"))
    result.add_argument("--max-pages", type=int, default=20)
    result.add_argument("--max-depth", type=int, default=1)
    result.add_argument("--confirm-risky-url", action="append", default=[], metavar="URL",
                        help="Exact reviewed URL permitted for navigation only; controls remain non-interactive.")
    return result


def main() -> None:
    args = parser().parse_args()
    if args.max_pages < 1 or args.max_depth < 0:
        parser().error("--max-pages must be positive and --max-depth cannot be negative")
    evidence = asyncio.run(crawl(args.cdp_url, args.start_url, args.output_dir, args.max_pages,
                                 args.max_depth, set(args.confirm_risky_url)))
    print(f"Read-only inventory complete: {len(evidence.pages)} page(s). Output: {args.output_dir}")


if __name__ == "__main__":
    main()

