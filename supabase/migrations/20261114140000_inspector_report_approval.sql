create table public.finding_review_records (
  id uuid primary key,
  tenant_id uuid not null references public.tenants(id),
  inspection_id uuid not null references public.inspections(id),
  media_asset_id uuid not null references public.media_assets(id),
  reviewer_id uuid not null references public.profiles(id),
  decision text not null check (decision in ('accepted', 'rejected', 'needs_verification')),
  payload jsonb not null check (jsonb_typeof(payload) = 'object'),
  reviewed_at timestamptz not null default now()
);

create table public.approved_report_snapshots (
  id uuid primary key,
  tenant_id uuid not null references public.tenants(id),
  inspection_id uuid not null references public.inspections(id),
  approved_by uuid not null references public.profiles(id),
  finding_ids uuid[] not null check (cardinality(finding_ids) between 1 and 200),
  snapshot jsonb not null check (jsonb_typeof(snapshot) = 'object'),
  approved_at timestamptz not null default now()
);

create index finding_reviews_inspection_idx on public.finding_review_records(tenant_id, inspection_id, id);
create index report_snapshots_inspection_idx on public.approved_report_snapshots(tenant_id, inspection_id, id);
create index analysis_jobs_inspection_page_idx on public.analysis_jobs(tenant_id, inspection_id, id);

alter table public.finding_review_records enable row level security;
alter table public.approved_report_snapshots enable row level security;
create policy finding_record_read on public.finding_review_records for select to authenticated
  using (tenant_id = public.current_tenant_id() and exists (
    select 1 from public.inspections where inspections.id = inspection_id and
      (assigned_inspector_id = auth.uid() or exists(select 1 from public.profiles where id = auth.uid() and role in ('admin', 'owner')))
  ));
create policy report_snapshot_read on public.approved_report_snapshots for select to authenticated
  using (tenant_id = public.current_tenant_id() and exists (
    select 1 from public.inspections where inspections.id = inspection_id and
      (assigned_inspector_id = auth.uid() or exists(select 1 from public.profiles where id = auth.uid() and role in ('admin', 'owner')))
  ));

revoke all on public.finding_review_records, public.approved_report_snapshots from anon, authenticated, service_role;
grant select on public.finding_review_records, public.approved_report_snapshots to authenticated;
grant select, insert on public.finding_review_records, public.approved_report_snapshots to service_role;

create function public.audit_inspector_approval()
returns trigger language plpgsql set search_path = '' as $$
begin
  insert into public.audit_events(tenant_id, actor_id, correlation_id, aggregate_type, aggregate_id, event_type)
  values (new.tenant_id,
    case when tg_table_name = 'finding_review_records' then (to_jsonb(new)->>'reviewer_id')::uuid else (to_jsonb(new)->>'approved_by')::uuid end,
    gen_random_uuid(), tg_table_name, new.id,
    case when tg_table_name = 'finding_review_records' then 'finding.reviewed' else 'report.approved' end);
  return new;
end $$;
revoke all on function public.audit_inspector_approval() from public;
create trigger finding_record_audit after insert on public.finding_review_records
  for each row execute function public.audit_inspector_approval();
create trigger report_snapshot_audit after insert on public.approved_report_snapshots
  for each row execute function public.audit_inspector_approval();

create function public.serialize_finding_review()
returns trigger language plpgsql set search_path = '' as $$
begin
  perform 1 from public.inspections where id = new.inspection_id and tenant_id = new.tenant_id for update;
  if not found then raise exception 'Inspection not found'; end if;
  perform 1 from public.media_assets where id = new.media_asset_id and inspection_id = new.inspection_id and tenant_id = new.tenant_id;
  if not found then raise exception 'Evidence belongs to another inspection'; end if;
  return new;
end $$;
revoke all on function public.serialize_finding_review() from public;
create trigger serialize_finding_review before insert on public.finding_review_records
  for each row execute function public.serialize_finding_review();

create function public.approve_inspector_report(p_report_id uuid, p_inspection_id uuid, p_tenant_id uuid, p_approver_id uuid, p_finding_ids uuid[])
returns jsonb language plpgsql set search_path = '' as $$
declare inspection public.inspections; existing public.approved_report_snapshots; findings jsonb; snapshot jsonb; client_name text;
begin
  select * into inspection from public.inspections where id = p_inspection_id and tenant_id = p_tenant_id for update;
  if inspection.id is null then return jsonb_build_object('error', 'Inspection not found.'); end if;
  perform 1 from public.profiles where id = p_approver_id and tenant_id = p_tenant_id and is_active
    and (role in ('owner', 'admin') or (role = 'inspector' and inspection.assigned_inspector_id = p_approver_id));
  if not found then return jsonb_build_object('error', 'Inspector authorization is required.'); end if;
  select * into existing from public.approved_report_snapshots where id = p_report_id and tenant_id = p_tenant_id;
  if existing.id is not null then
    if existing.inspection_id <> p_inspection_id or existing.approved_by <> p_approver_id or existing.finding_ids <> p_finding_ids then
      return jsonb_build_object('error', 'Approval retry payload changed.');
    end if;
    return existing.snapshot;
  end if;
  if p_finding_ids is null or cardinality(p_finding_ids) not between 1 and 200 or cardinality(p_finding_ids) <> (select count(distinct id) from unnest(p_finding_ids) as id) then
    return jsonb_build_object('error', 'Select between 1 and 200 distinct findings.');
  end if;
  if (select count(*) from public.finding_review_records where id = any(p_finding_ids) and tenant_id = p_tenant_id
    and inspection_id = p_inspection_id and decision = 'accepted') <> cardinality(p_finding_ids) then
    return jsonb_build_object('error', 'Only accepted findings from this inspection can be approved.');
  end if;
  if (select count(distinct media_asset_id) from public.finding_review_records where id = any(p_finding_ids)) <> cardinality(p_finding_ids) then
    return jsonb_build_object('error', 'Select only one reviewed finding per photo.');
  end if;
  if exists(select 1 from public.finding_review_records selected where selected.id = any(p_finding_ids)
    and exists(select 1 from public.finding_review_records newer where newer.tenant_id = p_tenant_id and newer.inspection_id = p_inspection_id
      and newer.media_asset_id = selected.media_asset_id and (newer.reviewed_at, newer.id) > (selected.reviewed_at, selected.id))) then
    return jsonb_build_object('error', 'A selected finding has a newer review. Refresh before approving.');
  end if;
  select jsonb_agg(payload || jsonb_build_object('id', id, 'inspection_id', inspection_id, 'reviewer_id', reviewer_id, 'reviewed_at', reviewed_at)
    order by array_position(p_finding_ids, id)) into findings from public.finding_review_records where id = any(p_finding_ids);
  select full_name into client_name from public.clients where id = inspection.client_id and tenant_id = p_tenant_id;
  snapshot := jsonb_build_object('id', p_report_id, 'inspection_id', p_inspection_id, 'property_address', coalesce(inspection.property_address, 'Not recorded'),
    'client_name', coalesce(client_name, 'Not recorded'), 'approved_by', p_approver_id, 'approved_at', now(), 'findings', findings);
  insert into public.approved_report_snapshots(id, tenant_id, inspection_id, approved_by, finding_ids, snapshot)
    values(p_report_id, p_tenant_id, p_inspection_id, p_approver_id, p_finding_ids, snapshot);
  return snapshot;
end $$;
revoke all on function public.approve_inspector_report(uuid, uuid, uuid, uuid, uuid[]) from public, anon, authenticated;
grant execute on function public.approve_inspector_report(uuid, uuid, uuid, uuid, uuid[]) to service_role;