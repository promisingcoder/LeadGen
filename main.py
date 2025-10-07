"""Command-line entry point for the lead harvesting workflow."""

from __future__ import annotations

import asyncio
import json
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Any, Dict, List

from lead_pipeline.pipeline import run_pipeline


def _serialize(results: Dict[str, List[Any]]) -> Dict[str, Any]:
    """Convert pydantic objects to plain dictionaries for reporting."""

    return {business: [contact.model_dump() for contact in contacts] for business, contacts in results.items()}


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Lead harvesting pipeline powered by Crawl4AI + GPT-4o")
    parser.add_argument("query", help='Google Maps query (e.g., "lawyers in New York, NY")')
    parser.add_argument("--output", help="Optional JSON file path for exporting JSON results")
    parser.add_argument(
        "--max-businesses",
        type=int,
        default=None,
        help="Limit processing to the first N businesses from Google Maps",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args: Namespace = parser.parse_args()

    results = asyncio.run(run_pipeline(args.query, max_businesses=args.max_businesses))
    serialized = _serialize(results)

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(json.dumps(serialized, indent=2))
        print(f"Saved {sum(len(v) for v in serialized.values())} contacts to {output_path}")
    else:
        print(json.dumps(serialized, indent=2))


if __name__ == "__main__":
    main()
