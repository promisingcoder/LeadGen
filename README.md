# Lead Harvest Pipeline

Automated workflow that discovers businesses from Google Maps, crawls their digital surface area with **Crawl4AI**, enriches contact data with **GPT-4o**, follows important external profiles, and persists findings to Supabase. The pipeline intentionally avoids CSS selectors and regex-based scraping—every extraction step relies on LLM reasoning.

## Features
- Google Maps semantic extraction for business listings.
- Intelligent link scoring to prioritize contact/team/leadership pages.
- Person-level contact parsing (names, roles, emails, phones, socials).
- External network enrichment (LinkedIn, Twitter, etc.).
- Wayback Machine snapshot traversal to recover historical details.
- Native Supabase upserts for business and contact tables with deduplication and field-level enrichment.

## Requirements
- Python 3.10+
- Access to the internet (blocked in this environment).
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

export SUPABASE_URL="https://xyzcompany.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="service-role-key"
export SUPABASE_BUSINESS_TABLE="businesses"    # optional
export SUPABASE_CONTACT_TABLE="contacts"       # optional

export CRAWL_MAX_INTERNAL_LINKS="15"           # optional tuning
export CRAWL_MAX_EXTERNAL_LINKS="10"
export CRAWL_LINK_CONCURRENCY="5"
export WAYBACK_SNAPSHOT_LIMIT="5"
export WAYBACK_YEARS_BACK="5"
export CRAWL_USE_CACHE="false"
```

## Running the Pipeline

```bash
python3 main.py "lawyers in New York, NY" --output leads.json
```

The command prints the structured contact map to stdout and (optionally) stores it to a JSON file. Results are also upserted into Supabase when the database credentials are provided.

## Supabase Schema Expectations

Create two tables (adjust names via env variables if needed):

```sql
create table businesses (
  id uuid primary key default gen_random_uuid(),
  name text,
  query text,
  address text,
  phone text,
  website text,
  google_maps_url text,
  rating numeric,
  review_count int,
  additional_metadata jsonb,
  inserted_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table contacts (
  id uuid primary key default gen_random_uuid(),
  business_name text,
  person_name text,
  position text,
  emails text[],
  phone_numbers text[],
  social_links text[],
  location text,
  notes text,
  source_url text,
  source_type text,
  snapshot_timestamp text,
  inserted_at timestamptz default now(),
  updated_at timestamptz default now()
);

create unique index contacts_dedupe_key
  on contacts (business_name, person_name, position, source_type, snapshot_timestamp);
```

## Wayback Machine Behavior
- The crawler visits `https://web.archive.org/web/*/<URL>` and uses GPT-4o to select the best snapshots within the configured time window.
- Each snapshot is crawled with the same person-level extraction strategy used on the live site.
- Contacts obtained from archives are flagged with `source_type = "wayback"` and carry a `snapshot_timestamp`.

## Notes & Limitations
- This environment cannot perform network calls; run the workflow on a machine with open network access.
- Google Maps content can change dynamically. Adjust the model temperature or instructions if extractions become noisy.
- Respect target-site Terms of Service and rate limits. Crawl4AI's adaptive link scorer already limits excess crawling, but you can further tune `max_links` and concurrency.
- Costs: GPT-4o extraction happens multiple times per business (homepage, contact pages, external profiles, snapshots). Monitor usage and consider batching queries.
- Deduplication merges newly discovered emails/phones/socials into existing contacts, so repeated runs enrich existing rows instead of creating duplicates.
