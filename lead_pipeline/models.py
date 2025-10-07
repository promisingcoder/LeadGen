"""Structured data models shared across the lead pipeline."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CrawlSource(str, Enum):
    """Source type used to separate internal, external, and archival data."""

    INTERNAL = "internal"
    EXTERNAL = "external"
    WAYBACK = "wayback"


class BusinessProfile(BaseModel):
    """Represents a single business discovered via Google Maps."""

    query: str = Field(description="Original Google Maps query that produced this business")
    name: str = Field(description="Business or firm name")
    address: Optional[str] = Field(default=None, description="Street address or service area")
    phone: Optional[str] = Field(default=None, description="Primary phone number if present")
    website: Optional[str] = Field(
        default=None, description="Canonical website extracted from Google Maps listing"
    )
    google_maps_url: str = Field(description="Direct link to the Google Maps listing")
    rating: Optional[float] = Field(default=None, description="Star rating if visible")
    review_count: Optional[int] = Field(default=None, description="Visible review count")
    additional_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Any extra attributes returned by the LLM extraction (e.g., hours, categories)",
    )


class ContactRecord(BaseModel):
    """Represents a person-level contact discovered during crawling."""

    business_name: str = Field(description="Business these contacts belong to")
    person_name: str = Field(description="Full name of the individual")
    position: Optional[str] = Field(default=None, description="Role or title inside the organization")
    emails: List[str] = Field(default_factory=list, description="Email addresses associated with the person")
    phone_numbers: List[str] = Field(default_factory=list, description="Phone numbers associated with the person")
    social_links: List[str] = Field(default_factory=list, description="Relevant social media or external links")
    location: Optional[str] = Field(default=None, description="Any location details mentioned with the person")
    notes: Optional[str] = Field(default=None, description="Supplemental notes provided by the LLM")
    source_url: str = Field(description="URL where the contact information was extracted from")
    source_type: CrawlSource = Field(
        default=CrawlSource.INTERNAL, description="Internal site, external network, or archival snapshot"
    )
    snapshot_timestamp: Optional[str] = Field(
        default=None, description="Wayback Machine timestamp when applicable (YYYYMMDDhhmmss)"
    )


class SnapshotRecord(BaseModel):
    """Metadata for a Wayback snapshot that should be crawled."""

    original_url: str
    snapshot_url: str
    timestamp: str
    source_type: CrawlSource = Field(default=CrawlSource.WAYBACK)
