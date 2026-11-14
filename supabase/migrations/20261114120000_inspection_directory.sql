create extension if not exists pg_trgm;

create table public.clients (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants (id) on delete restrict,
  full_name text not null check (char_length(btrim(full_name)) between 1 and 200),
  email text check (char_length(email) <= 320),
  created_at timestamptz not null default now(),
  unique (tenant_id, id)
);

create table public.properties (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants (id) on delete restrict,
  address_line1 text not null check (char_length(btrim(address_line1)) between 1 and 200),
  address_line2 text not null default '' check (char_length(address_line2) <= 200),
  city text not null check (char_length(btrim(city)) between 1 and 100),
  region text not null check (char_length(btrim(region)) between 1 and 100),
  postal_code text not null check (char_length(btrim(postal_code)) between 1 and 20),
  country text not null check (country in ('CA', 'US')),
  search_address text generated always as (
    address_line1 || ', ' || case when address_line2 = '' then '' else address_line2 || ', ' end
    || city || ', ' || region || ', ' || postal_code || ', ' || country
  ) stored,
  created_at timestamptz not null default now(),
  unique (tenant_id, id)
);

alter table public.inspections
  add column client_id uuid,
  add column property_id uuid,
  add constraint inspections_client_tenant_fk foreign key (tenant_id, client_id)
    references public.clients (tenant_id, id) on delete restrict,
  add constraint inspections_property_tenant_fk foreign key (tenant_id, property_id)
    references public.properties (tenant_id, id) on delete restrict;

create index properties_address_search_idx on public.properties using gin (search_address gin_trgm_ops);
create index inspections_tenant_id_idx on public.inspections (tenant_id, id);
create index inspections_tenant_assignee_id_idx on public.inspections (tenant_id, assigned_inspector_id, id);
create index inspections_tenant_client_id_idx on public.inspections (tenant_id, client_id, id);
create index inspections_tenant_property_id_idx on public.inspections (tenant_id, property_id, id);
create index media_assets_tenant_inspection_id_idx on public.media_assets (tenant_id, inspection_id, id);

alter table public.clients enable row level security;
alter table public.properties enable row level security;

create policy client_read on public.clients for select to authenticated
  using (tenant_id = public.current_tenant_id());
create policy property_read on public.properties for select to authenticated
  using (tenant_id = public.current_tenant_id());

revoke all on public.clients, public.properties from anon, authenticated;
grant select on public.clients, public.properties to authenticated;
grant select, insert on public.clients, public.properties to service_role;

create function public.search_inspection_properties(
  p_tenant_id uuid, p_limit integer default 50, p_after uuid default null, p_search text default null
)
returns setof public.properties
language sql stable
security invoker
set search_path = public, extensions
as $$
  select * from public.properties
  where tenant_id = p_tenant_id
    and (p_after is null or id > p_after)
    and (p_search is null or search_address ilike '%' ||
      replace(replace(replace(p_search, E'\\', E'\\\\'), '%', E'\\%'), '_', E'\\_') || '%')
  order by id
  limit greatest(1, least(p_limit, 100))
$$;

revoke all on function public.search_inspection_properties(uuid, integer, uuid, text) from public, anon, authenticated;
grant execute on function public.search_inspection_properties(uuid, integer, uuid, text) to service_role;