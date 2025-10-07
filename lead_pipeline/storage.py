"""Supabase persistence helpers."""

from __future__ import annotations

from typing import List, Optional

from supabase import Client, create_client

from .config import supabase_settings
from .models import BusinessProfile, ContactRecord


class SupabaseSink:
    """Thin wrapper around Supabase for persisting businesses and contacts."""

    def __init__(self) -> None:
        self._client: Optional[Client] = None
        if supabase_settings.url and supabase_settings.key:
            self._client = create_client(supabase_settings.url, supabase_settings.key)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def upsert_businesses(self, businesses: List[BusinessProfile]) -> None:
        if not businesses or not self._client:
            return

        payload = [
            {
                "name": business.name,
                "query": business.query,
                "address": business.address,
                "phone": business.phone,
                "website": business.website,
                "google_maps_url": business.google_maps_url,
                "rating": business.rating,
                "review_count": business.review_count,
                "additional_metadata": business.additional_metadata,
            }
            for business in businesses
        ]

        self._client.table(supabase_settings.business_table).upsert(payload)

    def upsert_contacts(self, contacts: List[ContactRecord]) -> None:
        if not contacts or not self._client:
            return

        payload = [
            {
                "business_name": contact.business_name,
                "person_name": contact.person_name or "",
                "position": contact.position or "",
                "emails": contact.emails,
                "phone_numbers": contact.phone_numbers,
                "social_links": contact.social_links,
                "location": contact.location,
                "notes": contact.notes,
                "source_url": contact.source_url,
                "source_type": contact.source_type.value,
                "snapshot_timestamp": contact.snapshot_timestamp or "",
            }
            for contact in contacts
        ]

        self._client.table(supabase_settings.contact_table).upsert(
            payload,
            on_conflict="business_name,person_name,position,source_type,snapshot_timestamp",
        )
