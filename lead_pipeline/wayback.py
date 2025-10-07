"""Wayback Machine snapshot discovery and enrichment."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import List, Optional
from urllib.parse import quote_plus

import httpx
from crawl4ai import AsyncWebCrawler, CacheMode, CrawlerRunConfig, LLMConfig, LLMExtractionStrategy
from pydantic import BaseModel, Field

from .config import crawl_settings, openai_settings
from .models import BusinessProfile, ContactRecord, CrawlSource, SnapshotRecord
from .site_crawler import extract_contacts_from_page


class SnapshotEntry(BaseModel):
    """Intermediate payload produced by the LLM."""

    original_url: str = Field(description="Original page URL captured by the snapshot")
    snapshot_url: str = Field(description="Direct Web Archive snapshot URL")
    timestamp: str = Field(description="Snapshot time in YYYYMMDDhhmmss format")


class SnapshotPayload(BaseModel):
    """Schema returned when extracting Wayback snapshot listings."""

    snapshots: List[SnapshotEntry] = Field(
        description="Chronologically sorted list of snapshots worth crawling"
    )


def _api_snapshot_lookup(target_url: str) -> List[SnapshotRecord]:
    """Use the Wayback Machine CDX API to fetch available snapshots."""

    params = {
        "url": target_url,
        "output": "json",
        "fl": "timestamp,original,statuscode",
        "filter": "statuscode:200",
        "collapse": "digest",
        "limit": str(max(crawl_settings.wayback_snapshot_limit * 3, 10)),
    }

    try:
        response = httpx.get("https://web.archive.org/cdx/search/cdx", params=params, timeout=15.0)
        response.raise_for_status()
    except httpx.HTTPError:
        return []

    data = response.json()
    if not data or len(data) <= 1:
        return []

    header = data[0]
    try:
        ts_idx = header.index("timestamp")
        url_idx = header.index("original")
    except ValueError:
        return []

    cutoff_year = datetime.utcnow().year - crawl_settings.wayback_years_back
    snapshots: List[SnapshotRecord] = []

    for row in data[1:]:
        if len(row) <= max(ts_idx, url_idx):
            continue
        timestamp = row[ts_idx]
        original_url = row[url_idx]
        if not timestamp or not original_url:
            continue
        try:
            year = int(timestamp[:4])
        except (ValueError, TypeError):
            continue
        if year < cutoff_year:
            continue
        snapshots.append(
            SnapshotRecord(
                original_url=original_url,
                snapshot_url=f"https://web.archive.org/web/{timestamp}/{original_url}",
                timestamp=timestamp,
                source_type=CrawlSource.WAYBACK,
            )
        )
        if len(snapshots) >= crawl_settings.wayback_snapshot_limit:
            break

    return snapshots


def _snapshot_strategy(target_url: str) -> LLMExtractionStrategy:
    """Build an LLM strategy that extracts relevant snapshots."""

    llm_cfg = LLMConfig(
        provider=openai_settings.model,
        api_token=openai_settings.api_key if openai_settings.api_key else "env:OPENAI_API_KEY",
        temperature=openai_settings.temperature,
        max_tokens=openai_settings.max_tokens,
    )

    start_year = (datetime.utcnow() - timedelta(days=365 * crawl_settings.wayback_years_back)).year
    current_year = datetime.utcnow().year

    instruction = f"""
    You are browsing the Wayback Machine listing for {target_url}.
    Identify up to {crawl_settings.wayback_snapshot_limit} snapshots between {start_year} and {current_year}.
    Prefer snapshots that are evenly spaced over time and have a successful status (HTTP 200 series).
    Return the canonical snapshot URL (https://web.archive.org/web/<timestamp>/<original_url>)
    and include the timestamp in YYYYMMDDhhmmss format.
    """

    schema = SnapshotPayload.model_json_schema()

    return LLMExtractionStrategy(
        llm_config=llm_cfg,
        schema=schema,
        extraction_type="schema",
        instruction=instruction,
        input_format="html",
        apply_chunking=True,
    )


async def discover_snapshots(target_url: str, crawler: AsyncWebCrawler) -> List[SnapshotRecord]:
    """Return prioritized Wayback snapshots for a website."""

    api_snapshots = _api_snapshot_lookup(target_url)
    if api_snapshots:
        return api_snapshots

    listing_url = f"https://web.archive.org/web/*/{quote_plus(target_url)}"
    config = CrawlerRunConfig(
        cache_mode=CacheMode.ENABLED if crawl_settings.use_cache else CacheMode.BYPASS,
        extraction_strategy=_snapshot_strategy(target_url),
    )

    result = await crawler.arun(listing_url, config=config)
    if not result.success or not result.extracted_content:
        return []

    try:
        payload = json.loads(result.extracted_content)
        parsed = SnapshotPayload.model_validate(payload)
    except (json.JSONDecodeError, ValueError):
        return []

    snapshots: List[SnapshotRecord] = []
    for entry in parsed.snapshots:
        timestamp = (entry.timestamp or "").strip()
        original_url = (entry.original_url or "").strip()
        snapshot_url = (entry.snapshot_url or "").strip()

        if not timestamp or not original_url:
            continue

        # Ensure we point to a concrete snapshot, not the listing page.
        if "*" in snapshot_url or timestamp not in snapshot_url:
            snapshot_url = f"https://web.archive.org/web/{timestamp}/{original_url}"

        snapshots.append(
            SnapshotRecord(
                original_url=original_url,
                snapshot_url=snapshot_url,
                timestamp=timestamp,
                source_type=CrawlSource.WAYBACK,
            )
        )

    snapshots.sort(key=lambda snap: snap.timestamp)
    return snapshots[: crawl_settings.wayback_snapshot_limit]


async def extract_contacts_from_snapshot(
    business: BusinessProfile,
    snapshot: SnapshotRecord,
    crawler: AsyncWebCrawler,
) -> List[ContactRecord]:
    """Extract contact records from a Wayback snapshot."""

    contacts = await extract_contacts_from_page(
        business=business,
        page_url=snapshot.snapshot_url,
        crawler=crawler,
        source_type=CrawlSource.WAYBACK,
        snapshot_ts=snapshot.timestamp,
    )

    # Tag notes to highlight archival provenance.
    for contact in contacts:
        if contact.notes:
            contact.notes = f"{contact.notes} (sourced from {snapshot.timestamp})"
        else:
            contact.notes = f"Sourced from {snapshot.timestamp}"
    return contacts
