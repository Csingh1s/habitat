alter table public.analysis_jobs add column lease_token uuid, add column lease_until timestamptz;
alter table public.media_assets add column inspector_note text not null default '' check (char_length(inspector_note) <= 1000);
alter table public.media_assets drop constraint media_assets_tenant_id_checksum_sha256_key;
create index media_assets_inspection_checksum_idx on public.media_assets(tenant_id, inspection_id, checksum_sha256);
update public.analysis_jobs set lease_until = now() - interval '1 second' where status = 'running';
create index analysis_jobs_worker_queue_idx on public.analysis_jobs(status, lease_until, created_at)
  where status in ('queued', 'running');

create function public.claim_inspection_analysis()
returns setof public.analysis_jobs language plpgsql set search_path = '' as $$
declare selected_id uuid;
begin
  update public.analysis_jobs set status = 'failed', error_code = 'Worker lease retry limit reached.', completed_at = now()
    where status = 'running' and lease_until < now() and retry_count >= 5;
  select id into selected_id from public.analysis_jobs
    where status = 'queued' or (status = 'running' and lease_until < now() and retry_count < 5)
    order by created_at for update skip locked limit 1;
  if selected_id is null then return; end if;
  return query update public.analysis_jobs set status = 'running', started_at = now(),
    lease_token = gen_random_uuid(), lease_until = now() + interval '5 minutes',
    retry_count = case when status = 'running' then retry_count + 1 else retry_count end
    where id = selected_id returning *;
end $$;

create function public.finish_inspection_analysis(p_job_id uuid, p_lease_token uuid, p_outcome text, p_error text, p_candidate jsonb)
returns boolean language plpgsql set search_path = '' as $$
declare job public.analysis_jobs;
begin
  select * into job from public.analysis_jobs where id = p_job_id for update;
  if job.id is null or job.status <> 'running' or p_lease_token is null or job.lease_token is distinct from p_lease_token
    or job.lease_until is null or job.lease_until <= now() then return false; end if;
  if p_outcome not in ('succeeded', 'blocked') then raise exception 'Invalid analysis outcome'; end if;
  if p_outcome = 'succeeded' then
    if p_candidate is null or p_candidate->>'requires_human_review' is distinct from 'true' then raise exception 'Human review is mandatory'; end if;
    insert into public.ai_review_candidates(id, tenant_id, analysis_job_id, media_asset_id, schema_version, model_id, model_version,
      category_candidate, component_candidate, visible_indicator_candidates, evidence_marker, draft_caption, draft_observation,
      confidence, uncertainty_reason, requires_human_review)
    values ((p_candidate->>'id')::uuid, job.tenant_id, job.id, job.media_asset_id, 'v1', job.model_id, job.model_version,
      p_candidate->>'category_candidate', p_candidate->>'component_candidate', p_candidate->'visible_indicator_candidates',
      nullif(p_candidate->'evidence_marker', 'null'::jsonb), p_candidate->>'draft_caption', p_candidate->>'draft_observation',
      (p_candidate->>'confidence')::numeric, p_candidate->>'uncertainty_reason', true);
  end if;
  update public.analysis_jobs set status = p_outcome::public.analysis_job_status, error_code = p_error,
    completed_at = now(), lease_until = null, lease_token = null where id = job.id;
  insert into public.audit_events(tenant_id, correlation_id, aggregate_type, aggregate_id, event_type)
    values (job.tenant_id, gen_random_uuid(), 'analysis_job', job.id, 'analysis.' || p_outcome);
  return true;
end $$;

create function public.complete_evidence_validation(p_media_id uuid, p_tenant_id uuid, p_sanitized_key text)
returns void language plpgsql set search_path = '' as $$
begin
  update public.media_assets set processing_status = 'ready_for_analysis', security_scan_status = 'clean',
    sanitized_object_key = p_sanitized_key, exif_sanitized_at = now(), updated_at = now()
    where id = p_media_id and tenant_id = p_tenant_id and processing_status in ('validation_queued', 'ready_for_analysis');
  if not found then raise exception 'Media cannot be validated'; end if;
  update public.media_validation_jobs set status = 'succeeded', completed_at = now()
    where media_asset_id = p_media_id and tenant_id = p_tenant_id;
end $$;

revoke all on function public.claim_inspection_analysis() from public, anon, authenticated;
revoke all on function public.finish_inspection_analysis(uuid, uuid, text, text, jsonb) from public, anon, authenticated;
revoke all on function public.complete_evidence_validation(uuid, uuid, text) from public, anon, authenticated;
grant execute on function public.claim_inspection_analysis() to service_role;
grant execute on function public.finish_inspection_analysis(uuid, uuid, text, text, jsonb) to service_role;
grant execute on function public.complete_evidence_validation(uuid, uuid, text) to service_role;

create function public.queue_evidence_validation(p_media_id uuid, p_tenant_id uuid, p_etag text)
returns jsonb language plpgsql set search_path = '' as $$
declare asset public.media_assets; queued public.media_validation_jobs; created boolean;
begin
  select * into asset from public.media_assets where id = p_media_id and tenant_id = p_tenant_id for update;
  if asset.id is null or asset.processing_status = 'rejected' then raise exception 'Media is unavailable'; end if;
  insert into public.media_validation_jobs(tenant_id, media_asset_id) values(p_tenant_id, p_media_id)
    on conflict(media_asset_id) do nothing returning * into queued;
  created := found;
  if not created then select * into queued from public.media_validation_jobs where media_asset_id = p_media_id and tenant_id = p_tenant_id; end if;
  update public.media_assets set storage_etag = p_etag,
    processing_status = case when processing_status = 'upload_pending' then 'validation_queued'::public.media_processing_status else processing_status end
    where id = p_media_id returning * into asset;
  return jsonb_build_object('job', to_jsonb(queued), 'created', created, 'processing_status', asset.processing_status);
end $$;
revoke all on function public.queue_evidence_validation(uuid, uuid, text) from public, anon, authenticated;
grant execute on function public.queue_evidence_validation(uuid, uuid, text) to service_role;