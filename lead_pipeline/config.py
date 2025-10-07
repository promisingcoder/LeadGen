"""Configuration helpers for the lead harvesting pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class OpenAISettings:
    """Settings for GPT-powered extraction."""

    model: str = os.getenv("OPENAI_MODEL", "openai/gpt-4o-mini")
    api_key: str = os.getenv("OPENAI_API_KEY", "")
    temperature: float = float(os.getenv("OPENAI_TEMPERATURE", "0.0"))
    max_tokens: int = int(os.getenv("OPENAI_MAX_TOKENS", "1800"))


@dataclass(frozen=True)
class SupabaseSettings:
    """Supabase connection details."""

    url: Optional[str] = os.getenv("SUPABASE_URL")
    key: Optional[str] = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    business_table: str = os.getenv("SUPABASE_BUSINESS_TABLE", "businesses")
    contact_table: str = os.getenv("SUPABASE_CONTACT_TABLE", "contacts")


@dataclass(frozen=True)
class CrawlSettings:
    """High-level crawling parameters."""

    max_internal_links: int = int(os.getenv("CRAWL_MAX_INTERNAL_LINKS", "15"))
    max_external_links: int = int(os.getenv("CRAWL_MAX_EXTERNAL_LINKS", "10"))
    link_concurrency: int = int(os.getenv("CRAWL_LINK_CONCURRENCY", "5"))
    wayback_snapshot_limit: int = int(os.getenv("WAYBACK_SNAPSHOT_LIMIT", "5"))
    wayback_years_back: int = int(os.getenv("WAYBACK_YEARS_BACK", "5"))
    use_cache: bool = os.getenv("CRAWL_USE_CACHE", "false").lower() == "true"


openai_settings = OpenAISettings()
supabase_settings = SupabaseSettings()
crawl_settings = CrawlSettings()
