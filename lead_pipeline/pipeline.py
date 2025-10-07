"""High-level orchestration for the lead harvesting flow."""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Tuple

from crawl4ai import AsyncWebCrawler, BrowserConfig

from .google_maps import extract_businesses
from .models import ContactRecord, CrawlSource
from .site_crawler import crawl_contact_surfaces, extract_contacts_from_page, score_site_links
from .storage import SupabaseSink
from .wayback import discover_snapshots, extract_contacts_from_snapshot


_NON_ALPHA = re.compile(r"[^a-z0-9]+")
_NON_DIGIT = re.compile(r"\D+")


def _normalize_name(name: Optional[str]) -> str:
    if not name:
        return ""
    collapsed = _NON_ALPHA.sub("", name.lower())
    return collapsed


def _normalize_emails(emails: Iterable[str]) -> Tuple[str, ...]:
    normalized = {email.strip().lower() for email in emails if email}
    return tuple(sorted(normalized))


def _normalize_phones(numbers: Iterable[str]) -> Tuple[str, ...]:
    cleaned = {_NON_DIGIT.sub("", number) for number in numbers if number}
    sanitized = {num.lstrip("0") or num for num in cleaned if num}
    return tuple(sorted(sanitized))


def _normalize_social_links(links: Iterable[str]) -> Tuple[str, ...]:
    normalized = {link.strip().lower() for link in links if link}
    return tuple(sorted(normalized))


def _contact_signature(contact: ContactRecord) -> Tuple:
    name_token = _normalize_name(contact.person_name)
    email_tokens = _normalize_emails(contact.emails)
    phone_tokens = _normalize_phones(contact.phone_numbers)
    social_tokens = _normalize_social_links(contact.social_links)

    if not name_token and email_tokens:
        name_token = email_tokens[0]
    if not name_token and phone_tokens:
        name_token = phone_tokens[0]

    return (
        contact.business_name.strip().lower(),
        name_token,
        email_tokens,
        phone_tokens,
        social_tokens,
        contact.position.strip().lower() if contact.position else "",
        contact.source_type.value,
        contact.snapshot_timestamp or "",
    )


def _merge_lists(primary: List[str], secondary: Iterable[str]) -> List[str]:
    """Append unique items from secondary into primary while preserving order."""

    seen = {item.lower() for item in primary if isinstance(item, str)}
    for item in secondary:
        if not item:
            continue
        lowered = item.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        primary.append(item)
    return primary


def _merge_contacts(base: ContactRecord, incoming: ContactRecord) -> None:
    """Enrich the base record with data from the incoming duplicate."""

    if not base.person_name and incoming.person_name:
        base.person_name = incoming.person_name
    if not base.position and incoming.position:
        base.position = incoming.position
    if not base.location and incoming.location:
        base.location = incoming.location

    base.emails = _merge_lists(list(base.emails), incoming.emails)
    base.phone_numbers = _merge_lists(list(base.phone_numbers), incoming.phone_numbers)
    base.social_links = _merge_lists(list(base.social_links), incoming.social_links)

    if incoming.notes:
        if base.notes and incoming.notes.lower() not in base.notes.lower():
            base.notes = f"{base.notes} | {incoming.notes}"
        elif not base.notes:
            base.notes = incoming.notes

    # Prefer the most detailed source URL when available.
    if incoming.source_url and incoming.source_url != base.source_url:
        if base.source_url:
            if base.notes:
                base.notes = f"{base.notes} | Additional source: {incoming.source_url}"
            else:
                base.notes = f"Additional source: {incoming.source_url}"
        else:
            base.source_url = incoming.source_url


def _deduplicate_contacts(contacts: Iterable[ContactRecord]) -> List[ContactRecord]:
    """Remove duplicates while merging any newly discovered information."""

    merged: Dict[Tuple, ContactRecord] = {}
    for contact in contacts:
        signature = _contact_signature(contact)
        existing = merged.get(signature)
        if existing:
            _merge_contacts(existing, contact)
        else:
            merged[signature] = contact
    return list(merged.values())


class LeadHarvestPipeline:
    """Coordinate business discovery, contact extraction, and persistence."""

    def __init__(self, supabase: Optional[SupabaseSink] = None) -> None:
        self.supabase = supabase or SupabaseSink()

    async def run(self, query: str, max_businesses: Optional[int] = None) -> Dict[str, List[ContactRecord]]:
        """Execute the full workflow for a single Google Maps query."""

        browser_config = BrowserConfig(headless=True, text_mode=False)
        async with AsyncWebCrawler(config=browser_config) as maps_crawler:
            businesses = await extract_businesses(query, maps_crawler)

        if max_businesses is not None:
            businesses = businesses[:max_businesses]

        if self.supabase.enabled:
            self.supabase.upsert_businesses(businesses)

        contact_map: Dict[str, List[ContactRecord]] = {}

        # Downstream crawling uses the lightweight default client to respect the
        # requirement that a browser session is only leveraged for Google Maps.
        async with AsyncWebCrawler() as crawler:
            for business in businesses:
                contacts: List[ContactRecord] = []

                if business.website:
                    homepage_contacts = await extract_contacts_from_page(
                        business=business,
                        page_url=business.website,
                        crawler=crawler,
                        source_type=CrawlSource.INTERNAL,
                    )
                    contacts.extend(homepage_contacts)

                    link_sets = await score_site_links(business, crawler)
                    surface_contacts = await crawl_contact_surfaces(
                        business=business,
                        crawler=crawler,
                        internal_links=link_sets.get("internal", []),
                        external_links=link_sets.get("external", []),
                    )
                    contacts.extend(surface_contacts)

                    snapshots = await discover_snapshots(business.website, crawler)
                    for snapshot in snapshots:
                        archival_contacts = await extract_contacts_from_snapshot(
                            business=business,
                            snapshot=snapshot,
                            crawler=crawler,
                        )
                        contacts.extend(archival_contacts)

                deduped = _deduplicate_contacts(contacts)
                contact_map[business.name] = deduped

                if self.supabase.enabled and deduped:
                    self.supabase.upsert_contacts(deduped)

        return contact_map


async def run_pipeline(query: str, max_businesses: Optional[int] = None) -> Dict[str, List[ContactRecord]]:
    """Convenience entry point."""

    pipeline = LeadHarvestPipeline()
    return await pipeline.run(query, max_businesses=max_businesses)
