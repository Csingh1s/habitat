# Habitat Inspection Workspace

React/TypeScript inspector workspace sharing the FastAPI inspection directory with mobile.
The connected workflow supports capture, AI drafts, inspector review, explicit approval,
and numbered photo PDFs. Local validation is not proof of a production deployment.

## Run

From the workspace root, start the API in one terminal:

```powershell
$env:APP_ENV = "development"
$env:PYTHONPATH = "$PWD\api\src"
py -3.13 -m uvicorn habitat_api.main:app --host 127.0.0.1 --port 8001
```

Start React in another terminal:

```powershell
cd web
npm install
npm run dev
```

Open http://127.0.0.1:5173. Vite binds to loopback and proxies `/api` to port 8001.
Demo tenant/user headers are added by the development proxy, not embedded in the browser.
The local API does not need additional CORS origins. Production builds use Microsoft Entra
MSAL access tokens and HTTPS. Configure the public build values in [`.env.example`](.env.example),
register the web origin as an Entra SPA redirect URI, and allow that origin in the API's
`DEPLOYED_CORS_ORIGINS` JSON array. Missing identity configuration fails closed.

## Available Workflows

- Create clients and structured property addresses.
- Create an inspection using existing records or new client/property details.
- Search property addresses through the API; filter clients and inspections within loaded pages.
- Follow a client or property to its inspection history.
- Open inspection details, copy record UUIDs, and load additional pages.
- Upload up to ten JPEG/PNG/WebP images per batch, each at most 25 MB, with a category,
  SHA-256 upload intent, storage upload, and completion confirmation.
- Retrieve authorized original photographs and mobile field notes after a reload.
- Request Qwen analysis and refresh the durable job status without treating AI output as approved.
- Save accepted, rejected, or needs-verification inspector findings with reviewed wording.
- Explicitly approve current accepted findings into an immutable snapshot and download its
    PDF with numbered photographs, captions, observations, approval identity, and timestamp.

Property searches debounce for 350 ms and require at least three characters. Directory pages
load 20 records. Client/property selectors initially load 100 records and offer additional
pages. Requests are cancelled when their view changes; stale pagination responses are ignored.
Uploads run sequentially rather than sending all file bytes concurrently.

Creation keys are retained across identical retries while the dialog remains open. Creating a
client, property, and inspection is three API operations, not one transaction. If a later step
fails, retry in the same dialog to reuse the previously created records. Closing the dialog or
changing a payload does not roll back records already created.

Original photos use authenticated API delivery and temporary object URLs revoked on unmount.
Deployed original delivery and review require clean evidence validation. A queued job is not
a claim that scanning or AI has finished. Report PDFs are generated from saved approved
snapshots only, never directly from model output or unsaved editor text. Save findings before
refreshing or changing the selected photograph; unsaved editor text is not durable.

The development API is in-memory: records reset when its process restarts and remote Qwen
calls remain blocked. Production requires the Supabase migrations, private storage, OIDC,
a continuously available durable worker, and a private ClamAV scanner documented in
[`../api/README.md`](../api/README.md). Real database isolation/concurrency, deployed identity,
scanner, worker, provider execution, and representative PDF/load limits must be verified in
staging before release. PDF downloads have a two-minute client timeout; infrastructure timeouts
must accommodate generation. Large reports may require durable asynchronous PDF rendering.
Homeowner signup, sharing/delivery, and Tarion submission are not implemented here.
Nothing in the UI submits a claim or enables remote inference.

## Validation

```powershell
npm run test
npm run lint
npm run build
```

The API-client tests cover pagination, retry keys, errors, image validation, checksum and
completion, resumed uploads, bounded PDF timeouts, and unexpected upload destinations.
Local browser testing connected web creation to mobile capture and web review/approval/PDF.
The successful inference path uses a mock in API tests, not a live provider.
