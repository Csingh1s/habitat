alter table public.profiles
  drop constraint if exists profiles_id_fkey;

alter table public.profiles
  add column identity_issuer text,
  add column identity_subject text,
  add column email text,
  add column country text,
  add column region text;

create unique index profiles_identity_subject_idx
  on public.profiles (identity_issuer, identity_subject)
  where identity_issuer is not null and identity_subject is not null;

create or replace function public.onboard_entra_identity(
  p_user_id uuid,
  p_identity_issuer text,
  p_identity_subject text,
  p_email text,
  p_display_name text,
  p_company_name text,
  p_country text,
  p_region text
)
returns public.profiles
language plpgsql
security definer
set search_path = ''
as $$
declare
  existing_profile public.profiles;
  new_tenant_id uuid;
begin
  select *
  into existing_profile
  from public.profiles
  where identity_issuer = p_identity_issuer
    and identity_subject = p_identity_subject;

  if found then
    return existing_profile;
  end if;

  insert into public.tenants (name, data_region)
  values (
    p_company_name,
    case when p_country = 'Canada' then 'ca' else 'us' end
  )
  returning id into new_tenant_id;

  insert into public.profiles (
    id,
    tenant_id,
    display_name,
    role,
    identity_issuer,
    identity_subject,
    email,
    country,
    region
  )
  values (
    p_user_id,
    new_tenant_id,
    p_display_name,
    'owner',
    p_identity_issuer,
    p_identity_subject,
    p_email,
    p_country,
    p_region
  )
  returning * into existing_profile;

  return existing_profile;
end;
$$;

revoke all on function public.onboard_entra_identity(
  uuid, text, text, text, text, text, text, text
) from public;
