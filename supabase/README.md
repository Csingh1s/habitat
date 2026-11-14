# Supabase foundation

This folder defines the shared PostgreSQL and private image-storage foundation for Habitat
Inspector. It is suitable for a Supabase free-tier development project and can migrate later to
managed PostgreSQL and S3-compatible storage without changing the domain model.

## Before creating a project

- Use a company-owned Supabase organization, not a personal account.
- Select the data region deliberately. Customer evidence, addresses, and reports are sensitive.
- Do not put a Supabase `service_role` key in the Expo mobile app, browser code, source control,
  chat, or screenshots.
- The `inspection-evidence` bucket is private by design. The API creates short-lived signed
  upload URLs after it authorizes the tenant, user, and inspection.

## Create and link the Supabase project

1. Create a new Supabase project in the Supabase dashboard.
2. Install the Supabase CLI using the method appropriate for the development machine.
3. From the workspace root, authenticate interactively:

   ```powershell
   npx supabase login
   ```

4. Link the local migration directory to the new project using the project reference shown in
   the Supabase dashboard:

   ```powershell
   npx supabase link --project-ref YOUR_PROJECT_REF
   ```

5. Review the migration carefully, then apply it:

   ```powershell
   npx supabase db push
   ```

The initial migration is
[`20261018160000_initial_habitat_schema.sql`](./migrations/20261018160000_initial_habitat_schema.sql).
The follow-up
[`20261111170000_media_persistence_support.sql`](./migrations/20261111170000_media_persistence_support.sql)
adds durable idempotency records, the requested inspection category, and storage ETag tracking
needed by the FastAPI Supabase adapters.

## Security model

- Every exposed application table has Row Level Security enabled.
- Authenticated users can read only records in their own `tenant_id`.
- The mobile app does not receive direct write permissions for inspections, reports, media,
  candidates, or audit events.
- FastAPI uses a server-only service-role secret to authorize workflow transitions and generate
  signed storage URLs. A service-role secret bypasses RLS, so it must never leave the API
  service.
- Audit events intentionally have no update or delete policy.
- No policy permits direct `storage.objects` access. The bucket is private and upload access is
  granted by short-lived, tenant-scoped signed URLs.

## Next implementation step

After the Supabase project exists, configure the API with its server-only URL and service-role
secret in a local ignored environment file or deployment secret manager. Then replace the
development `InMemoryRepository` and `InMemoryObjectStore` with Supabase/PostgreSQL and Storage
adapters. The Expo app must use normal user authentication and never contain a service-role key.
