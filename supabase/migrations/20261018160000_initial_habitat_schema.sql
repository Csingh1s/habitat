create extension if not exists pgcrypto;

create type public.member_role as enum (
  'owner',
  'admin',
  'inspector',
  'reviewer',
  'operations'
);

create type public.inspection_status as enum (
  'scheduled',
  'in_progress',
  'ready_for_review',
  'completed',
  'cancelled'
);

create type public.media_processing_status as enum (
  'upload_pending',
  'validation_queued',
  'ready_for_analysis',
  'rejected'
);

create type public.analysis_job_status as enum (
  'queued',
  'running',
  'succeeded',
  'blocked',
  'failed'
);

create type public.review_decision as enum (
  'accepted_unchanged',
  'accepted_edited',
  'rejected',
  'needs_verification'
);

create type public.report_status as enum (
  'draft',
  'review_required',
  'approved',
  'published',
  'archived'
);

create table public.tenants (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(name) between 1 and 200),
  data_region text not null default 'us',
  created_at timestamptz not null default now()
);

create table public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  tenant_id uuid not null references public.tenants (id) on delete restrict,
  display_name text not null check (char_length(display_name) between 1 and 200),
  role public.member_role not null default 'inspector',
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.inspections (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants (id) on delete restrict,
  assigned_inspector_id uuid references public.profiles (id) on delete set null,
  status public.inspection_status not null default 'scheduled',
  service_template_version text not null check (char_length(service_template_version) between 1 and 100),
  scheduled_for timestamptz,
  property_address text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index inspections_tenant_status_idx
  on public.inspections (tenant_id, status, scheduled_for desc);

create table public.media_assets (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants (id) on delete restrict,
  inspection_id uuid not null references public.inspections (id) on delete restrict,
  created_by uuid not null references public.profiles (id) on delete restrict,
  original_object_key text not null unique,
  sanitized_object_key text unique,
  thumbnail_object_key text unique,
  file_name text not null check (char_length(file_name) between 1 and 255),
  content_type text not null check (content_type in ('image/jpeg', 'image/png', 'image/webp')),
  content_length bigint not null check (content_length > 0 and content_length <= 25000000),
  checksum_sha256 text not null check (checksum_sha256 ~ '^[a-f0-9]{64}$'),
  perceptual_hash text,
  capture_timestamp timestamptz not null,
  processing_status public.media_processing_status not null default 'upload_pending',
  security_scan_status text not null default 'pending'
    check (security_scan_status in ('pending', 'clean', 'quarantined', 'failed')),
  exif_sanitized_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, checksum_sha256)
);

create index media_assets_inspection_created_idx
  on public.media_assets (tenant_id, inspection_id, created_at desc);

create table public.media_validation_jobs (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants (id) on delete restrict,
  media_asset_id uuid not null unique references public.media_assets (id) on delete restrict,
  status public.analysis_job_status not null default 'queued',
  error_code text,
  created_at timestamptz not null default now(),
  completed_at timestamptz
);

create table public.analysis_jobs (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants (id) on delete restrict,
  inspection_id uuid not null references public.inspections (id) on delete restrict,
  media_asset_id uuid not null references public.media_assets (id) on delete restrict,
  requested_category text,
  model_policy_version text not null,
  model_id text not null,
  model_version text not null,
  status public.analysis_job_status not null default 'queued',
  retry_count integer not null default 0 check (retry_count >= 0 and retry_count <= 5),
  error_code text,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz
);

create index analysis_jobs_media_created_idx
  on public.analysis_jobs (tenant_id, media_asset_id, created_at desc);

create table public.ai_review_candidates (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants (id) on delete restrict,
  analysis_job_id uuid not null unique references public.analysis_jobs (id) on delete restrict,
  media_asset_id uuid not null references public.media_assets (id) on delete restrict,
  schema_version text not null,
  model_id text not null,
  model_version text not null,
  category_candidate text,
  component_candidate text,
  visible_indicator_candidates jsonb not null default '[]'::jsonb
    check (jsonb_typeof(visible_indicator_candidates) = 'array'),
  evidence_marker jsonb,
  draft_caption text not null,
  draft_observation text,
  confidence numeric(4, 3) not null check (confidence >= 0 and confidence <= 1),
  uncertainty_reason text not null,
  requires_human_review boolean not null default true check (requires_human_review),
  created_at timestamptz not null default now()
);

create table public.suggestion_reviews (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants (id) on delete restrict,
  suggestion_id uuid not null references public.ai_review_candidates (id) on delete restrict,
  reviewer_id uuid not null references public.profiles (id) on delete restrict,
  decision public.review_decision not null,
  edited_values jsonb,
  review_reason text,
  created_at timestamptz not null default now()
);

create index suggestion_reviews_suggestion_created_idx
  on public.suggestion_reviews (tenant_id, suggestion_id, created_at desc);

create table public.reports (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants (id) on delete restrict,
  inspection_id uuid not null unique references public.inspections (id) on delete restrict,
  status public.report_status not null default 'draft',
  approved_by uuid references public.profiles (id) on delete set null,
  approved_at timestamptz,
  published_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (
    (status not in ('approved', 'published'))
    or (approved_by is not null and approved_at is not null)
  )
);

create table public.report_items (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants (id) on delete restrict,
  report_id uuid not null references public.reports (id) on delete cascade,
  source_suggestion_id uuid references public.ai_review_candidates (id) on delete set null,
  category text not null,
  component text,
  location text,
  wording text not null,
  recommendation text,
  created_by uuid not null references public.profiles (id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index report_items_report_created_idx
  on public.report_items (tenant_id, report_id, created_at);

create table public.audit_events (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants (id) on delete restrict,
  actor_id uuid references public.profiles (id) on delete set null,
  correlation_id uuid not null,
  aggregate_type text not null,
  aggregate_id uuid not null,
  event_type text not null,
  metadata_redacted jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null default now()
);

create index audit_events_tenant_aggregate_idx
  on public.audit_events (tenant_id, aggregate_type, aggregate_id, occurred_at desc);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger profiles_set_updated_at
  before update on public.profiles
  for each row execute procedure public.set_updated_at();

create trigger inspections_set_updated_at
  before update on public.inspections
  for each row execute procedure public.set_updated_at();

create trigger media_assets_set_updated_at
  before update on public.media_assets
  for each row execute procedure public.set_updated_at();

create trigger reports_set_updated_at
  before update on public.reports
  for each row execute procedure public.set_updated_at();

create trigger report_items_set_updated_at
  before update on public.report_items
  for each row execute procedure public.set_updated_at();

create or replace function public.current_tenant_id()
returns uuid
language sql
stable
security definer
set search_path = ''
as $$
  select profiles.tenant_id
  from public.profiles
  where profiles.id = auth.uid()
    and profiles.is_active = true
$$;

revoke all on function public.current_tenant_id() from public;
grant execute on function public.current_tenant_id() to authenticated;

alter table public.tenants enable row level security;
alter table public.profiles enable row level security;
alter table public.inspections enable row level security;
alter table public.media_assets enable row level security;
alter table public.media_validation_jobs enable row level security;
alter table public.analysis_jobs enable row level security;
alter table public.ai_review_candidates enable row level security;
alter table public.suggestion_reviews enable row level security;
alter table public.reports enable row level security;
alter table public.report_items enable row level security;
alter table public.audit_events enable row level security;

create policy tenant_read on public.tenants
  for select to authenticated
  using (id = public.current_tenant_id());

create policy profile_read on public.profiles
  for select to authenticated
  using (tenant_id = public.current_tenant_id());

create policy inspection_read on public.inspections
  for select to authenticated
  using (tenant_id = public.current_tenant_id());

create policy media_asset_read on public.media_assets
  for select to authenticated
  using (tenant_id = public.current_tenant_id());

create policy media_validation_job_read on public.media_validation_jobs
  for select to authenticated
  using (tenant_id = public.current_tenant_id());

create policy analysis_job_read on public.analysis_jobs
  for select to authenticated
  using (tenant_id = public.current_tenant_id());

create policy ai_review_candidate_read on public.ai_review_candidates
  for select to authenticated
  using (tenant_id = public.current_tenant_id());

create policy suggestion_review_read on public.suggestion_reviews
  for select to authenticated
  using (tenant_id = public.current_tenant_id());

create policy report_read on public.reports
  for select to authenticated
  using (tenant_id = public.current_tenant_id());

create policy report_item_read on public.report_items
  for select to authenticated
  using (tenant_id = public.current_tenant_id());

create policy audit_event_read on public.audit_events
  for select to authenticated
  using (tenant_id = public.current_tenant_id());

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'inspection-evidence',
  'inspection-evidence',
  false,
  25000000,
  array['image/jpeg', 'image/png', 'image/webp']
)
on conflict (id) do update
set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

-- No storage.objects policy is intentionally created. Browsers and mobile clients may upload
-- only through short-lived signed URLs created by the server-side FastAPI service role.
