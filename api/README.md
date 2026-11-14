# Habitat Image Analysis API

FastAPI foundation for secure home-inspection image evidence ingestion.

## Client, property, and inspection directory

The existing API now owns the client -> inspection <- property relationship. A property
can have multiple inspections and different clients over time. Address text is a search
field, not an identifier or an authorization credential. UUIDs identify all three records.
No additional API service or duplicate photo upload is required.

| Method | Path | Purpose |
| --- | --- | --- |
| POST / GET | `/v1/clients` | Create / list company clients |
| GET | `/v1/clients/{client_id}` | Retrieve a client |
| POST / GET | `/v1/properties` | Create / search properties with `?search=Brampton` |
| GET | `/v1/properties/{property_id}` | Retrieve a structured address |
| POST / GET | `/v1/inspections` | Create / list authorized inspections |
| GET | `/v1/inspections/{inspection_id}` | Retrieve one authorized inspection |
| GET | `/v1/clients/{client_id}/inspections` | Client inspection history |
| GET | `/v1/properties/{property_id}/inspections` | Property inspection history |
| GET | `/v1/inspections/{inspection_id}/media` | Photo metadata without object keys or image bytes |

All lists return arrays, default to 50 records, and accept `limit=1..100` and `after=<last UUID>`.
Results are ordered by UUID, not appointment time. Request the next page using the last
record's `id`; an empty page ends traversal. `/v1/inspections` also accepts `client_id` and
`property_id` filters. Address searches require 3-200 non-blank characters and match a literal
case-insensitive substring, not wildcard expressions.

Creation requires an `Idempotency-Key` header (8-255 characters). Use a new random key for
each intentional create operation, and retain it across retries. A retry by the same user,
tenant, and resource type returns the same record; changing its payload returns HTTP 409.
Concurrent Supabase retries use atomic conflict handling instead of a check-then-insert race.
These are create-only endpoints; retry keys are not an update mechanism.

Example request bodies, in order:

```json
{"full_name":"Example Client","email":"client@example.com"}
```

```json
{"address_line1":"100 Example Street","address_line2":"Unit 2","city":"Brampton","region":"ON","postal_code":"A1A 1A1","country":"CA"}
```

```json
{"client_id":"<returned client UUID>","property_id":"<returned property UUID>","scheduled_for":"2026-11-20T15:00:00Z"}
```

New inspections are assigned to the caller. Inspectors see assigned inspections; company
owners/admins can access all company inspections. Clients and property addresses are shared
within a company. Reviewers cannot create records. A foreign tenant's UUID never grants
access, including when the caller is an admin in a different company. The development demo
inspection is seeded into this directory and continues to use the existing upload endpoints.

### Persistent deployment and performance

Apply [`20261114120000_inspection_directory.sql`](../supabase/migrations/20261114120000_inspection_directory.sql)
to a staging database before deploying this API version with `PERSISTENCE_BACKEND=supabase`.
Existing inspections keep nullable client/property links until explicitly backfilled; this
migration does not infer a client from an address or rewrite inspection history.

The migration adds tenant-qualified foreign keys, tenant-scoped read policies, service-only
writes, B-tree indexes for pagination/relationships, and a trigram index for address search.
Search uses a parameterized database function restricted to the service role. Photo lists
do not fetch storage objects, sign a URL for every image, or run AI. Authorized image delivery
and approved PDF generation use separate endpoints. Development data remains in memory and
resets when the process restarts; it is not durable production storage.

Run the API on a free local port and measure four requests per second over real HTTP:

```powershell
$env:APP_ENV = "development"
py -3.13 -m uvicorn habitat_api.main:app --host 127.0.0.1 --port 8001
# In another terminal, from the workspace root:
py -3.13 api/tools/load_directory.py --base-url http://127.0.0.1:8001 --rate 4 --requests 40
```

The check creates one synthetic client/property/inspection and alternates address searches,
client history, inspection details, and media lists. It reuses HTTP connections, sends up to
eight concurrent requests, and fails on HTTP errors, less than 95% of the target completion
rate, or p95 latency above 500 ms. Synthetic records remain until the local API restarts.
This verifies a small local in-memory workload, not production capacity or a rate limiter.
Before selling a production SLA, apply the migration, verify isolation against real Supabase,
and repeat representative staging load tests with realistic record counts and network latency.

The directory is shared by mobile capture and web findings/report workflows below.
Homeowner signup, sharing, and Tarion submission remain outside these endpoints.

## Implemented Phase 0-1 boundaries

- Versioned FastAPI contract under `/v1`.
- Development-only identity adapter.
- Tenant-scoped inspection authorization.
- Idempotent media upload intents.
- Direct-upload abstraction that returns a local development URL.
- Upload completion guarded by checksum and an object-store head check.
- Media validation job queue boundary.
- Asynchronous Qwen2.5-VL review-candidate job contract and result polling.
- Immutable-style audit-event recording.
- Typed Pydantic contracts and tests.

## Security boundary

The development identity adapter requires `X-Dev-Tenant-Id` and `X-Dev-User-Id`. It is
enabled only when `APP_ENV=development`. Other environments validate user access tokens
against the configured OIDC issuer, audience, and JWKS and enforce company/inspection access.
They refuse startup without Supabase persistence, worker execution, and a private ClamAV host.

Uploads go directly to private storage. The durable worker verifies checksum/type/dimensions,
scans original bytes, and creates a sanitized inference image. Authorized photo/PDF retrieval
is delivered through FastAPI and requires a clean scan outside development. Service-role and
model credentials stay server-side; browser and mobile carry only user access tokens.

## Inspector review and approved reports

Create a client/property/inspection on web or through the directory API. The inspection is
assigned to its creator and appears in mobile. Select that inspection before capture; upload
the photograph and inspector note, then request analysis. Qwen produces a draft requiring
human review, not an approved finding. Web can review the draft or save an explicit manual
finding when the provider is unavailable.

- `GET /v1/inspections/{id}/analyses`: paginated evidence-linked jobs and candidates.
- `GET /v1/media/{id}/content`: authorized original photograph.
- `GET/POST /v1/inspections/{id}/findings`: append-only inspector review records.
- `GET/POST /v1/inspections/{id}/reports`: immutable approved snapshots; POST requires
	`inspector_approved=true` and 1-200 current accepted finding UUIDs, one per photograph.
- `GET /v1/reports/{id}` and `GET /v1/reports/{id}/pdf`: authorized snapshot and numbered
	photo report using saved reviewed wording. Rejected or superseded reviews cannot be approved.

Apply every migration in [`../supabase/migrations/`](../supabase/migrations/) in order, including
the inspector approval and durable-worker migrations. Approval is serialized against finding
writes by an inspection lock. Workers claim five-minute leases with bounded retries and
lease-token fencing. These new RPCs/grants/RLS and concurrency behavior must be verified
against real PostgreSQL; mocked/local tests do not establish database deployment correctness.

Configure deployed API and worker processes using [`.env.example`](.env.example):

```text
APP_ENV=staging
PERSISTENCE_BACKEND=supabase
INFERENCE_EXECUTION_MODE=worker
CLAMAV_HOST=private-scanner-hostname
CLAMAV_PORT=3310
DEPLOYED_CORS_ORIGINS=["https://YOUR_WEB_HOST"]
```

Supply the existing Supabase/OIDC/model configuration through server secrets. Run a separate
continuously available process with `python -m habitat_api.worker` (or
`habitat-analysis-worker`). The current worker is sequential, not an autoscaling service.
Provision the scanner privately, update virus signatures, monitor queue depth/job failures,
and verify recovery after worker termination. An API that scales to zero does not wake this
worker. Never expose the ClamAV TCP port publicly. Remote inference remains disabled until
an operator explicitly authorizes `ENABLE_REMOTE_INFERENCE=true` in staging/production.

Before release, prove real Entra tenant isolation, private storage, scanner rejection/outage,
lease recovery, live provider output, immutable approval, and PDF access. Test realistic report
sizes and Unicode wording: current PDF fonts do not guarantee every glyph, and synchronous
rendering is not a proven large-report service. The prior four-RPS test covers only the local
directory, not model throughput or deployed PDF capacity.

## Qwen inference endpoint

The self-hosted option uses a private OpenAI-compatible GPU endpoint serving
`Qwen/Qwen2.5-VL-3B-Instruct`. An explicitly configured Qwen Cloud option is described below.
Neither downloads model weights into the API process. Set provider values only in a server
secret manager or deployment configuration, never in source control:

The deployable vLLM service package is in [`../qwen-service/`](../qwen-service/). It is a
separate GPU workload with its own Runpod Pod configuration and secret boundary.

```text
QWEN_INFERENCE_URL=https://private-gpu.example/v1/chat/completions
QWEN_INFERENCE_API_KEY=...
QWEN_MODEL_ID=Qwen/Qwen2.5-VL-3B-Instruct
QWEN_MODEL_VERSION=your-immutable-deployment-version
```

### Qwen Cloud managed API

For lower-volume testing, the API can call Qwen Cloud's managed `qwen3.7-flash` vision model
instead of a self-hosted GPU Pod. The current Qwen Cloud model page lists image input and
structured outputs, with an OpenAI-compatible API endpoint in Singapore. Configure the deployed
FastAPI service only:

```text
INFERENCE_PROVIDER=qwen_cloud
DASHSCOPE_API_KEY=...
QWEN_CLOUD_INFERENCE_URL=https://ap-southeast-1.maas.qwencloudapi.com/compatible-mode/v1/chat/completions
QWEN_CLOUD_MODEL_ID=qwen3.7-flash
QWEN_CLOUD_MODEL_VERSION=qwen-cloud-managed
```

`DASHSCOPE_API_KEY` is accepted as the provider's documented key name. It must be stored only
in the server-side secret manager. The Qwen Cloud API key, like a self-hosted GPU key, must
never be included in the mobile app or source control.

Unpaid/free API quota is for public, synthetic, or non-sensitive test evidence only. Before
using authorized client evidence, use the paid API and complete the required data-processing,
data-region, retention, and consent review.

### Cost guard: local development never calls the model

The API fails closed by default. `APP_ENV=development` blocks remote Qwen requests even when
an endpoint URL and key happen to exist in the local environment. This lets engineers run,
test, and debug FastAPI from VS Code without starting or billing a GPU Pod.

Remote inference requires **all** of the following in the deployed staging or production API
service:

```text
APP_ENV=staging or APP_ENV=production
ENABLE_REMOTE_INFERENCE=true
QWEN_INFERENCE_URL=https://private-gpu.example/v1/chat/completions
QWEN_INFERENCE_API_KEY=...
```

`ENABLE_REMOTE_INFERENCE` defaults to `false`; deployed environments remain model-disabled
until an authorized operator explicitly enables it. Never set that flag or the GPU credentials
in the mobile app or a local development environment.

After a verified upload, create an analysis with
`POST /v1/media/{media_asset_id}/analyses` and poll
`GET /v1/analyses/{analysis_id}`. Results are schema-validated review candidates only:
they can flag possible visible cues, but cannot diagnose a defect, decide severity, recommend
a repair, or publish a report. If the Qwen endpoint is unavailable or not configured, the job
is marked `blocked` with an explicit message.

## Supabase shared-data foundation

The production-oriented PostgreSQL schema, private `inspection-evidence` storage bucket, and
tenant Row Level Security policies live in [`../supabase/`](../supabase/). The development
in-memory adapters remain active until the deployed API is configured with:

```text
PERSISTENCE_BACKEND=supabase
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...
SUPABASE_STORAGE_BUCKET=inspection-evidence
```

The service-role key is server-only and bypasses database Row Level Security. It must be held
only in Azure Container Apps/Key Vault secrets, never in the mobile app, browser code, source
control, or Supabase client configuration.

## Microsoft Entra and Azure staging

Microsoft Entra External ID setup instructions are in
[`ENTRA_EXTERNAL_ID_SETUP.md`](./ENTRA_EXTERNAL_ID_SETUP.md). Azure Container Apps deployment
files and the required Key Vault secret names are in [`../infra/azure/`](../infra/azure/).
That earlier API-only template does not provision the required worker/scanner or supply
their new configuration; it is not a complete deployment of this workflow. Update the
infrastructure and verify staging before release, rather than weakening startup gates.

## Local run

Requires Python 3.12+.

```powershell
cd api
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
$env:APP_ENV = "development"
uvicorn habitat_api.main:app --reload
```

For the connected web/mobile workspace use `--port 8001` and open
<http://127.0.0.1:8001/docs>.

## Local mobile end-to-end testing

Development mode includes one isolated **demo inspection** for `demo-tenant` /
`demo-inspector`. It is seeded in memory only when `APP_ENV=development`; the endpoint
`GET /development/demo-inspection` is unavailable in other environments.

The development upload emulator writes received test image bytes under
`api/.data/uploads/`. This directory is intentionally local-only and is not production object
storage. Delete it when local test evidence is no longer needed.

For an Android emulator, start the API on the loopback address:

```powershell
cd api
$env:APP_ENV = "development"
uvicorn habitat_api.main:app --host 127.0.0.1 --port 8001
```

Android uses `http://10.0.2.2:8001` to reach this computer's loopback service. The mobile
configuration is documented in [`mobile/.env.example`](../mobile/.env.example). The mobile
client uses development identity headers only when `EXPO_PUBLIC_HABITAT_API_MODE=development`;
these values must never be included in a production build.

For local authenticated calls, include:

```text
X-Dev-Tenant-Id: demo-tenant
X-Dev-User-Id: demo-inspector
```

## Test

```powershell
python -m pytest
```
