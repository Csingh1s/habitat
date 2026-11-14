# Azure staging deployment

This is an earlier API-only template, not a deployable configuration for the current connected
inspection workflow. The API now requires `INFERENCE_EXECUTION_MODE=worker` and a private
`CLAMAV_HOST` outside development; neither is supplied here. Before using the commands below,
update the deployment to run the durable worker continuously, provision a private scanner with
signature updates, supply their configuration, and apply all Supabase migrations. The API
intentionally fails closed until those settings are supplied. Do not disable these gates to
make this older template start. See [`../../api/README.md`](../../api/README.md).

This package deploys the FastAPI service to Azure Container Apps with scale-to-zero enabled.
It uses a system-assigned managed identity to read required server secrets from Azure Key Vault.

## What this deploys

- Azure Container Apps environment.
- One external FastAPI Container App on HTTPS.
- Health probes against `GET /health`.
- Zero minimum replicas and a maximum of three replicas.
- System-assigned managed identity with the **Key Vault Secrets User** role.

It does not deploy a GPU, database, or model server. PostgreSQL/private image storage remain in
Supabase; AI remains in Qwen Cloud.

## Prerequisites the account owner must configure

1. Azure subscription and a staging resource group.
2. Azure CLI login:

   ```powershell
   az login
   az account set --subscription "YOUR_SUBSCRIPTION_NAME_OR_ID"
   ```

3. Microsoft Entra External ID API registration:
   - Add an API scope, for example `access_as_user`.
   - Record the issuer, audience/Application ID URI, and JWKS URL from the OpenID discovery
     document. These are configuration values, not application secrets.
4. An existing Azure Key Vault in the same subscription with these secret names:

   ```text
   supabase-url
   supabase-service-role-key
   dashscope-api-key
   ```

   Do not put secret values in Bicep parameters, mobile app configuration, source code, or chat.
5. A registry image built from [`../../api/Dockerfile`](../../api/Dockerfile), published to a
   registry Azure Container Apps can pull.

## Build and publish the FastAPI image

From the workspace root, use a registry you own. Example shape:

```powershell
docker build --platform linux/amd64 --tag YOUR_REGISTRY/habitat-api:staging .\api
docker push YOUR_REGISTRY/habitat-api:staging
```

Configure registry pull authentication separately if the image is private. Do not make a
production API image public just to simplify staging.

## Deploy

```powershell
az group create --name habitat-inspector-staging --location eastus

az deployment group create `
  --resource-group habitat-inspector-staging `
  --template-file .\infra\azure\main.bicep `
  --parameters `
    containerImage=YOUR_REGISTRY/habitat-api:staging `
    keyVaultName=YOUR_KEY_VAULT_NAME `
    oidcIssuerUrl="YOUR_ENTRA_ISSUER_URL" `
    oidcAudience="YOUR_API_APPLICATION_ID_URI" `
    oidcJwksUrl="YOUR_ENTRA_JWKS_URL"
```

The deployment output prints `apiUrl`. Set that value in the mobile staging configuration as
`EXPO_PUBLIC_HABITAT_API_BASE_URL`. It is public configuration, not a secret.

## Required staging verification

1. `GET /health` responds with HTTP 200.
2. An Entra access token is rejected when expired, from the wrong issuer, or for the wrong
   audience.
3. An authenticated new user completes `POST /v1/onboarding`.
4. `GET /v1/inspections` returns only that tenant's inspections.
5. An authorized non-sensitive image uploads to private Supabase Storage, creates an analysis
   job, and returns an evidence-linked review candidate from Qwen Cloud.
6. Confirm a candidate cannot publish or deliver a report without a later human-review action.
