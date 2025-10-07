"""Utility script to backfill Supabase tables from a saved leads JSON file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

from lead_pipeline.models import BusinessProfile, ContactRecord, CrawlSource
from lead_pipeline.storage import SupabaseSink


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import lead contacts into Supabase from a JSON export.")
    parser.add_argument(
        "--input",
        required=True,
        help="Path to leads JSON (output of main.py).",
    )
    parser.add_argument(
        "--default-query",
        default="",
        help="Query string to associate with business records when the JSON does not include metadata.",
    )
    return parser


def load_contacts(path: Path) -> Dict[str, List[dict]]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("Leads JSON must be a JSON object keyed by business name.")
    return {business: entries or [] for business, entries in data.items()}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    sink = SupabaseSink()
    if not sink.enabled:
        raise RuntimeError("Supabase client is not configured. Check SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.")

    input_path = Path(args.input)
    contacts_map = load_contacts(input_path)

    businesses: List[BusinessProfile] = []
    contacts: List[ContactRecord] = []

    for business_name, entries in contacts_map.items():
        businesses.append(
            BusinessProfile(
                query=args.default_query,
                name=business_name,
                address=None,
                phone=None,
                website=None,
                google_maps_url="",
                rating=None,
                review_count=None,
                additional_metadata={},
            )
        )
        for entry in entries:
            try:
                source_type = CrawlSource(entry.get("source_type", CrawlSource.INTERNAL.value))
            except ValueError:
                source_type = CrawlSource.INTERNAL

            contacts.append(
                ContactRecord(
                    business_name=business_name,
                    person_name=entry.get("person_name", "").strip(),
                    position=entry.get("position"),
                    emails=entry.get("emails", []),
                    phone_numbers=entry.get("phone_numbers", []),
                    social_links=entry.get("social_links", []),
                    location=entry.get("location"),
                    notes=entry.get("notes"),
                    source_url=entry.get("source_url", ""),
                    source_type=source_type,
                    snapshot_timestamp=entry.get("snapshot_timestamp"),
                )
            )

    sink.upsert_businesses(businesses)
    sink.upsert_contacts(contacts)

    print(f"Imported {len(businesses)} businesses and {len(contacts)} contacts into Supabase.")


if __name__ == "__main__":
    main()
