"""Website crawling and contact extraction primitives."""

from __future__ import annotations

import json
from typing import Dict, Iterable, List, Optional

from crawl4ai import AsyncWebCrawler, CacheMode, CrawlerRunConfig, LLMConfig, LLMExtractionStrategy
from crawl4ai.adaptive_crawler import LinkPreviewConfig
from pydantic import BaseModel, Field

from .config import crawl_settings, openai_settings
from .models import BusinessProfile, ContactRecord, CrawlSource


class PersonPayload(BaseModel):
    """Serialized structure returned by LLM for contact extraction."""

    full_name: str = Field(description="Full name of the person")
    position: Optional[str] = Field(default=None, description="Role or title if mentioned")
    emails: List[str] = Field(default_factory=list, description="Email addresses associated with the person")
    phone_numbers: List[str] = Field(default_factory=list, description="Phone numbers listed for the person")
    social_links: List[str] = Field(
        default_factory=list,
        description="Social media or external profile links that belong to the person",
    )
    location: Optional[str] = Field(default=None, description="Location or office assignment if provided")
    notes: Optional[str] = Field(default=None, description="Any extra helpful context about the person")


class ContactPayload(BaseModel):
    """Wrapper used by the LLM extraction to return structured contacts."""

    people: List[PersonPayload] = Field(description="List of unique contacts discovered on the page")


def _contact_strategy(business: BusinessProfile, page_url: str) -> LLMExtractionStrategy:
    """Create an LLM extraction strategy tailored for person-level contact discovery."""

    llm_cfg = LLMConfig(
        provider=openai_settings.model,
        api_token=openai_settings.api_key if openai_settings.api_key else "env:OPENAI_API_KEY",
        temperature=openai_settings.temperature,
        max_tokens=openai_settings.max_tokens,
    )

    instruction = f"""
    You are researching staff members for {business.name}.
    Extract contact-level information for everyone mentioned on this page.
    Focus on unique people, their roles, and any contact methods (emails, phone numbers, messaging links).
    Ignore generic department phone numbers unless they are clearly tied to a specific person.
    Ignore non-human entities.
    Convert phone numbers to international format when possible.
    Return only structured JSON that matches the provided schema.
    """

    return LLMExtractionStrategy(
        llm_config=llm_cfg,
        schema=ContactPayload.model_json_schema(),
        extraction_type="schema",
        instruction=instruction,
        input_format="markdown",
        apply_chunking=True,
        chunk_token_threshold=1600,
    )


def build_link_preview_config() -> LinkPreviewConfig:
    """Adaptive link scoring tuned for contact discovery."""

    return LinkPreviewConfig(
        include_internal=True,
        include_external=True,
        max_links=crawl_settings.max_internal_links + crawl_settings.max_external_links,
        concurrency=crawl_settings.link_concurrency,
        query="contact team partner attorney staff profile bio leadership phone email office location",
        score_threshold=0.25,
        verbose=True,
    )


def _split_links(links: Optional[Dict[str, List[Dict[str, str]]]]) -> Dict[str, List[str]]:
    """Extract high-scoring internal and external links from the crawler response."""

    if not links:
        return {"internal": [], "external": []}

    def _normalize(link: Dict[str, str]) -> Optional[tuple[str, float]]:
        url = link.get("url") or link.get("href")
        if not url:
            return None
        if not url.startswith(("http://", "https://")):
            return None
        score = float(link.get("total_score") or link.get("intrinsic_score") or 0.0)
        return url, score

    def _rank(items: List[Dict[str, str]]) -> List[str]:
        normalized = []
        seen: set[str] = set()
        for item in items:
            pair = _normalize(item)
            if not pair:
                continue
            url, score = pair
            if url in seen:
                continue
            seen.add(url)
            normalized.append((url, score))
        normalized.sort(key=lambda entry: entry[1], reverse=True)
        return [url for url, _ in normalized]

    internal = _rank(links.get("internal", []))
    external = _rank(links.get("external", []))
    return {
        "internal": internal[: crawl_settings.max_internal_links],
        "external": external[: crawl_settings.max_external_links],
    }


async def score_site_links(
    business: BusinessProfile,
    crawler: AsyncWebCrawler,
) -> Dict[str, List[str]]:
    """Score internal/external links to prioritize contact pages."""

    if not business.website:
        return {"internal": [], "external": []}

    config = CrawlerRunConfig(
        cache_mode=CacheMode.ENABLED if crawl_settings.use_cache else CacheMode.BYPASS,
        link_preview_config=build_link_preview_config(),
        score_links=True,
    )

    response = await crawler.arun(business.website, config=config)
    return _split_links(response.links if response else None)


async def extract_contacts_from_page(
    business: BusinessProfile,
    page_url: str,
    crawler: AsyncWebCrawler,
    source_type: CrawlSource,
    snapshot_ts: Optional[str] = None,
) -> List[ContactRecord]:
    """Extract structured contact records from a single page."""

    config = CrawlerRunConfig(
        cache_mode=CacheMode.ENABLED if crawl_settings.use_cache else CacheMode.BYPASS,
        extraction_strategy=_contact_strategy(business, page_url),
    )

    result = await crawler.arun(page_url, config=config)
    if not result.success or not result.extracted_content:
        return []

    try:
        raw = json.loads(result.extracted_content)
        if isinstance(raw, list):
            combined = {"people": []}
            for item in raw:
                if isinstance(item, dict) and "people" in item:
                    combined["people"].extend(item["people"])
            raw = combined
        payload = ContactPayload.model_validate(raw)
    except (json.JSONDecodeError, ValueError):
        return []

    contacts: List[ContactRecord] = []
    for person in payload.people:
        contacts.append(
            ContactRecord(
                business_name=business.name,
                person_name=person.full_name,
                position=person.position,
                emails=person.emails,
                phone_numbers=person.phone_numbers,
                social_links=person.social_links,
                location=person.location,
                notes=person.notes,
                source_url=page_url,
                source_type=source_type,
                snapshot_timestamp=snapshot_ts,
            )
        )
    return contacts


async def crawl_contact_surfaces(
    business: BusinessProfile,
    crawler: AsyncWebCrawler,
    internal_links: Iterable[str],
    external_links: Iterable[str],
) -> List[ContactRecord]:
    """Crawl prioritized links and return aggregated contacts."""

    records: List[ContactRecord] = []

    for internal_url in internal_links:
        contacts = await extract_contacts_from_page(
            business=business,
            page_url=internal_url,
            crawler=crawler,
            source_type=CrawlSource.INTERNAL,
        )
        records.extend(contacts)

    for external_url in external_links:
        contacts = await extract_contacts_from_page(
            business=business,
            page_url=external_url,
            crawler=crawler,
            source_type=CrawlSource.EXTERNAL,
        )
        records.extend(contacts)

    return records
