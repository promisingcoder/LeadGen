-- Enable UUID helper for default IDs
create extension if not exists "pgcrypto";

-- Business listings table
create table if not exists public.businesses (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  query text,
  address text,
  phone text,
  website text,
  google_maps_url text,
  rating numeric,
  review_count integer,
  additional_metadata jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- Person-level contacts table
create table if not exists public.contacts (
  id uuid primary key default gen_random_uuid(),
  business_name text not null,
  person_name text not null,
  position text,
  emails text[] default '{}',
  phone_numbers text[] default '{}',
  social_links text[] default '{}',
  location text,
  notes text,
  source_url text not null,
  source_type text not null,
  snapshot_timestamp text,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  constraint contacts_source_type_check
    check (source_type in ('internal', 'external', 'wayback'))
);

-- Ensure a single row per Maps listing when URL available
create unique index if not exists businesses_unique_map_url
  on public.businesses (google_maps_url)
  where google_maps_url is not null;

-- Deduplication key used by the pipeline
create unique index if not exists contacts_dedupe_key
  on public.contacts (
    business_name,
    person_name,
    coalesce(position, ''),
    source_type,
    coalesce(snapshot_timestamp, '')
  );
