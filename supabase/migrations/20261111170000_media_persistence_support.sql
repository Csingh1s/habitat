alter table public.media_assets
  add column requested_category text;

alter table public.media_assets
  add column storage_etag text;

create table public.api_idempotency_keys (
  tenant_id uuid not null references public.tenants (id) on delete restrict,
  operation text not null check (char_length(operation) between 1 and 100),
  idempotency_key text not null check (char_length(idempotency_key) between 8 and 255),
  resource_id uuid not null,
  created_at timestamptz not null default now(),
  primary key (tenant_id, operation, idempotency_key)
);

create index api_idempotency_keys_resource_idx
  on public.api_idempotency_keys (tenant_id, resource_id);

alter table public.api_idempotency_keys enable row level security;

create policy api_idempotency_key_read on public.api_idempotency_keys
  for select to authenticated
  using (tenant_id = public.current_tenant_id());
