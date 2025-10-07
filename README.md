# Lead Harvest Pipeline

LLM-first workflow that finds businesses on Google Maps, explores their web footprint with **Crawl4AI**, enriches person-level contacts using **GPT-4o-mini**, and saves everything to Supabase—no CSS selectors or regex. The crawler also revisits every discovered URL through the Wayback Machine (CDX API + HTML fallback) so historical snapshots enhance each contact record.

## Highlights
- Google Maps extraction by parsing the raw `APP_INITIALIZATION_STATE` payloads.
- Adaptive link scoring to surface contact/team/practice pages and relevant external profiles.
- Contact enrichment (names, roles, emails, phones, socials) powered exclusively by GPT prompts.
- Wayback enrichment for each internal/external URL using timestamped snapshot URLs (wildcard listings are never crawled).
- Supabase persistence with merge-safe upserts for both businesses and contacts.

## Requirements
- Python 3.10+
- Access to the internet (blocked in some testing environments).
- API keys:
  - `OPENAI_API_KEY` (GPT-4o or compatible model).
  - `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` (or `SUPABASE_ANON_KEY` for testing).

Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Environment Variables

```bash
export OPENAI_API_KEY="sk-..."
export OPENAI_MODEL="openai/gpt-4o"            # optional (defaults to gpt-4o)
export OPENAI_TEMPERATURE="0.0"                # optional
export OPENAI_MAX_TOKENS="1800"                # optional

export SUPABASE_URL="https://your-project.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="service-role-key"
export SUPABASE_BUSINESS_TABLE="businesses"    # optional override
export SUPABASE_CONTACT_TABLE="contacts"       # optional override

export CRAWL_MAX_INTERNAL_LINKS="15"           # optional tuning
export CRAWL_MAX_EXTERNAL_LINKS="10"
export CRAWL_LINK_CONCURRENCY="5"
export WAYBACK_SNAPSHOT_LIMIT="5"
export WAYBACK_YEARS_BACK="5"
export CRAWL_USE_CACHE="false"
```

## Quick Start

1. **Clone & install** (see commands above).
2. **Initialize Supabase tables** by running the SQL in [`schema.sql`](schema.sql) inside the Supabase SQL editor (or via psql). This creates the `businesses`/`contacts` tables and the dedupe index the pipeline expects.
3. **Create `.env`** with the environment variables shown above (OpenAI key required; Supabase strongly recommended).
4. **Run a test crawl**:

   ```bash
   python3 main.py "lawyers in New York, NY" --max-businesses 1 --output leads.json
   ```

   The command prints results to stdout, writes `leads.json`, and upserts into Supabase. Increase `--max-businesses` when you’re satisfied with the output.

### Importing an existing JSON file

To backfill Supabase from a saved export:

```bash
python import_to_supabase.py --input leads_single.json --default-query "lawyers in New York, NY"
```

This script replays the JSON produced by `main.py`, creating minimal business rows (using `--default-query`) and merging contacts.

## Supabase Schema

For reference, `schema.sql` creates:

```sql
create table public.businesses (
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

create table public.contacts (
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

create unique index if not exists businesses_unique_map_url
  on public.businesses (google_maps_url) where google_maps_url is not null;

create unique index if not exists contacts_dedupe_key
  on public.contacts (business_name, person_name, coalesce(position, ''), source_type, coalesce(snapshot_timestamp, ''));
```

## Wayback Machine Behavior
- First tries the CDX API to pull timestamped snapshots; falls back to the HTML listing if the API returns nothing.
- Every archived URL is crawled via `https://web.archive.org/web/<timestamp>/<original>` (no wildcard pages).
- Wayback-derived contacts are labelled `source_type = "wayback"` with `snapshot_timestamp` set to the exact capture time.
- **Status:** Functional but still maturing—expect longer runtimes and occasional low-signal snapshots on certain sites.

## Notes & Limitations
- The pipeline relies on GPT-driven extraction only—no CSS selectors or regex are used for data parsing.
- Runs have been validated end-to-end on a single firm (Google Maps → site + socials → Supabase). Scale cautiously and monitor OpenAI rate limits.
- Wayback-derived data is experimental; verify archival contacts manually before consuming them in production workflows.
- Heavy Wayback usage can slow runs considerably—keep `WAYBACK_SNAPSHOT_LIMIT` tuned appropriately for your rate/usage budget.
- Google Maps content can change dynamically. Adjust the model temperature or instructions if extractions become noisy.
- Respect target-site Terms of Service and rate limits. Crawl4AI's adaptive link scorer already limits excess crawling, but you can further tune `max_links` and concurrency.
- Costs: LLM extraction happens multiple times per business (homepage, contact pages, external profiles, snapshots). Monitor usage and consider batching queries.
- Deduplication merges newly discovered emails/phones/socials into existing contacts, so repeated runs enrich existing rows instead of creating duplicates.
