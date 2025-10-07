"""Google Maps semantic extraction helpers."""

from __future__ import annotations

import json
from typing import List, Optional
from urllib.parse import quote_plus

from crawl4ai import AsyncWebCrawler, CacheMode, CrawlerRunConfig, LLMConfig, LLMExtractionStrategy
from pydantic import BaseModel, Field

from .config import crawl_settings, openai_settings
from .models import BusinessProfile


class GoogleMapsExtraction(BaseModel):
    """Schema returned by the LLM when parsing Google Maps SERP pages."""

    businesses: List[BusinessProfile] = Field(
        description="All businesses visible on the Google Maps results page"
    )


def _maps_extraction_strategy(query: str) -> LLMExtractionStrategy:
    """Configure an LLM extraction strategy tailored for Google Maps."""

    llm_cfg = LLMConfig(
        provider=openai_settings.model,
        api_token=openai_settings.api_key if openai_settings.api_key else "env:OPENAI_API_KEY",
        temperature=openai_settings.temperature,
        max_tokens=openai_settings.max_tokens,
    )

    instruction = f"""
    You are parsing a Google Maps search results page for the query: {query}.
    Google often embeds the structured results inside JavaScript variables such as
    APP_INITIALIZATION_STATE or other JSON snippets—extract businesses from those data
    blobs even if the DOM does not show the listings directly.
    Extract detailed business listings that appear in the result set.
    Prioritize the first 12 high-confidence businesses to stay within token limits.
    For each business include:
    - name of the business or firm exactly as shown.
    - street address or service area description if present.
    - phone number in international format if shown.
    - official website URL if available.
    - direct Google Maps listing link (ensure it's a complete URL).
    - rating (numeric) and review count when present.
    Capture any additional metadata that could help sales teams (categories, highlights, opening hours)
    inside the additional_metadata field.
    Only return structured JSON that matches the provided schema.
    """

    return LLMExtractionStrategy(
        llm_config=llm_cfg,
        schema=GoogleMapsExtraction.model_json_schema(),
        extraction_type="schema",
        instruction=instruction,
        input_format="html",
        apply_chunking=True,
        chunk_token_threshold=1200,
        overlap_rate=0.1,
    )


def _extract_payload_fragment(html: Optional[str], limit: int = 60000) -> Optional[str]:
    """Return a trimmed payload focusing on the embedded initialization state."""

    if not html:
        return None

    marker = "APP_INITIALIZATION_STATE="
    if marker not in html:
        # Fallback to leading slice of the document
        return html[:limit]

    start = html.find(marker)
    end = html.find("</script>", start)
    if end == -1:
        end = start + limit

    fragment = html[start:end]
    if len(fragment) > limit:
        fragment = fragment[:limit]

    return fragment


async def extract_businesses(
    query: str,
    crawler: AsyncWebCrawler,
) -> List[BusinessProfile]:
    """Run a Google Maps search and return structured businesses."""

    search_url = f"https://www.google.com/maps/search/{quote_plus(query)}"
    crawl_config = CrawlerRunConfig(
        cache_mode=CacheMode.ENABLED if crawl_settings.use_cache else CacheMode.BYPASS,
        wait_for="css:.Nv2PK",
        wait_for_timeout=20000,
        simulate_user=True,
        magic=True,
        scan_full_page=True,
        scroll_delay=0.4,
        remove_overlay_elements=True,
    )

    page_result = await crawler.arun(search_url, config=crawl_config)
    if not page_result.success:
        return []

    fragment = _extract_payload_fragment(page_result.html)
    if not fragment:
        fragment = _extract_payload_fragment(page_result.cleaned_html)
    if not fragment:
        fragment = _extract_payload_fragment(page_result.markdown.raw_markdown if page_result.markdown else None)
    if not fragment:
        return []

    raw_payload = (
        f"Query: {query}\n"
        "Extract the structured business listings from the following Google Maps data snippet. "
        "The content may be truncated—focus on the first visible businesses.\n\n"
        f"{fragment}"
    )

    extraction_config = CrawlerRunConfig(
        cache_mode=CacheMode.ENABLED if crawl_settings.use_cache else CacheMode.BYPASS,
        extraction_strategy=_maps_extraction_strategy(query),
    )

    result = await crawler.arun(f"raw://{raw_payload}", config=extraction_config)
    if not result.success or not result.extracted_content:
        return []

    try:
        payload = json.loads(result.extracted_content)
    except json.JSONDecodeError:
        return []

    if isinstance(payload, dict):
        entries = payload.get("businesses", [])
    elif isinstance(payload, list):
        if payload and isinstance(payload[0], dict) and "businesses" in payload[0]:
            entries = payload[0].get("businesses", [])
        else:
            entries = payload
    else:
        entries = []

    contacts: List[BusinessProfile] = []
    for entry in entries:
        try:
            contacts.append(BusinessProfile.model_validate(entry))
        except Exception:
            continue
    return contacts
