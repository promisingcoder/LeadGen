"""Supabase persistence helpers."""

from __future__ import annotations

from typing import List, Optional

from postgrest.exceptions import APIError
from supabase import Client, create_client

from .config import supabase_settings
from .models import BusinessProfile, ContactRecord, CrawlSource


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

        try:
            self._client.table(supabase_settings.business_table).upsert(
                payload, on_conflict="google_maps_url"
            ).execute()
        except APIError as api_exc:
            if api_exc.code in {"42P10", "23505"}:
                for entry in payload:
                    try:
                        gm_url = entry.get("google_maps_url")
                        if gm_url:
                            existing = (
                                self._client.table(supabase_settings.business_table)
                                .select("id")
                                .eq("google_maps_url", gm_url)
                                .limit(1)
                                .execute()
                            )
                            if existing.data:
                                self._client.table(supabase_settings.business_table).update(entry).eq(
                                    "google_maps_url", gm_url
                                ).execute()
                                continue
                        # Insert when no match by URL (including null URLs)
                        self._client.table(supabase_settings.business_table).insert(entry).execute()
                    except Exception as inner_exc:  # pragma: no cover
                        raise RuntimeError("Failed to upsert businesses into Supabase") from inner_exc
            else:  # pragma: no cover
                raise RuntimeError("Failed to upsert businesses into Supabase") from api_exc
        except Exception as exc:  # pragma: no cover - pass through for visibility
            raise RuntimeError("Failed to upsert businesses into Supabase") from exc

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

        try:
            self._client.table(supabase_settings.contact_table).upsert(
                payload,
                on_conflict="business_name,person_name,position,source_type,snapshot_timestamp",
            ).execute()
        except APIError as api_exc:
            if api_exc.code in {"42P10", "23505"}:
                for entry in payload:
                    try:
                        key_filters = {
                            "business_name": entry["business_name"],
                            "person_name": entry.get("person_name", ""),
                            "position": entry.get("position", ""),
                            "source_type": entry.get("source_type", CrawlSource.INTERNAL.value),
                            "snapshot_timestamp": entry.get("snapshot_timestamp", ""),
                        }

                        query = self._client.table(supabase_settings.contact_table).select("id").limit(1)
                        for column, value in key_filters.items():
                            query = query.eq(column, value)
                        existing = query.execute()

                        table_ref = self._client.table(supabase_settings.contact_table)
                        if existing.data:
                            update_builder = table_ref.update(entry)
                            update_builder = update_builder.eq("business_name", key_filters["business_name"])\
                                                         .eq("person_name", key_filters["person_name"])\
                                                         .eq("position", key_filters["position"])\
                                                         .eq("source_type", key_filters["source_type"])\
                                                         .eq("snapshot_timestamp", key_filters["snapshot_timestamp"])
                            update_builder.execute()
                        else:
                            table_ref.insert(entry).execute()
                    except Exception as inner_exc:  # pragma: no cover
                        raise RuntimeError("Failed to upsert contacts into Supabase") from inner_exc
            else:  # pragma: no cover
                raise RuntimeError("Failed to upsert contacts into Supabase") from api_exc
        except Exception as exc:  # pragma: no cover - pass through for visibility
            raise RuntimeError("Failed to upsert contacts into Supabase") from exc
