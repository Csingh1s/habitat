# Habitat Inspector Mobile

Cross-platform React Native/Expo application for field inspectors. It currently provides a
professional foundation for:

- A daily inspection queue.
- Camera permission handling and image-library selection.
- Direct camera capture into an evidence-review flow.
- Horizon-aligned inspection categories: Roofing, Exterior, Structure, Electrical, Heating,
  Cooling, Insulation, Plumbing, and Interior.
- Inspector notes and a secure-analysis staging state.
- Explicit human-review messaging: model output is a review candidate, never a final finding.
- Compact sign-in and workspace-registration screens with company name, full name, email,
  password, and country-aware U.S. state or Canadian province/territory selection.

## Run locally

```powershell
cd mobile
npm install
npm run android
# On macOS: npm run ios
npm run web
```

## Test the complete local evidence flow

1. Start the development API from the workspace:

   ```powershell
   cd ..\api
   $env:APP_ENV = "development"
   py -3.13 -m uvicorn habitat_api.main:app --host 127.0.0.1 --port 8000
   ```

2. Configure this mobile app using the supplied example:

   ```powershell
   cd ..\mobile
   Copy-Item .env.example .env.local
   ```

   `http://10.0.2.2:8000` is correct for the Android Studio emulator. For the web preview,
   use `http://127.0.0.1:8000`. For a physical Android phone, use the computer's LAN IP,
   bind the API explicitly to that LAN interface, and test only on a trusted private network.

3. Restart Expo after changing `.env.local`, choose a JPEG, PNG, or WebP photo, and press
   **Analyze photo**.

The local API seeds a non-customer demo inspection. It creates a secure upload intent,
verifies the file SHA-256 checksum, writes test files to `api/.data/uploads/`, confirms the
upload, and queues analysis. Without a configured private Qwen endpoint, the app correctly
shows **analysis unavailable** rather than inventing an inspection result.

## Azure staging / production API connection

The Expo client is ready to call a deployed HTTPS FastAPI service without changing upload,
completion, analysis, or polling logic. Copy [`.env.staging.example`](./.env.staging.example)
to an ignored environment file after Azure Container Apps provides an HTTPS URL:

```text
EXPO_PUBLIC_HABITAT_API_BASE_URL=https://api-staging.example.com
EXPO_PUBLIC_HABITAT_API_MODE=deployed
```

These are public app configuration values, not credentials. A deployed app must obtain a
short-lived user access token through the future OIDC login flow, then call
`configureAuthenticatedApiSession({ accessToken, inspectionId })` after the user selects an
authorized inspection. The API client sends that token as `Authorization: Bearer ...`.

The client refuses to upload in deployed mode until a runtime user session and inspection are
present. It never uses the development headers outside development and never embeds a Supabase
service-role key, Qwen/DashScope key, database password, or Azure secret.

The current sign-in and registration screens are UI and client-side validation only. The next
authentication milestone replaces their local transition with OIDC sign-in, server-side account
creation, email verification, and tenant/profile provisioning.

## Microsoft Entra External ID

The app now includes a PKCE authorization-code client for Microsoft Entra External ID. Enable it
only in the staging/production configuration by supplying these public values:

```text
EXPO_PUBLIC_ENTRA_CLIENT_ID=<mobile public-client application ID>
EXPO_PUBLIC_ENTRA_ISSUER_URL=<issuer from Entra discovery metadata>
EXPO_PUBLIC_ENTRA_API_SCOPE=api://<Habitat API application ID>/access_as_user
```

The access token is stored only through Expo SecureStore on Android/iOS. The mobile app does
not contain a client secret. The Entra tenant/API registration steps are in
[`../api/ENTRA_EXTERNAL_ID_SETUP.md`](../api/ENTRA_EXTERNAL_ID_SETUP.md).

## Production model boundary

The mobile client must not contain Qwen weights or call a model provider directly. It sends
an authenticated, staged evidence request to the backend after media is uploaded securely.
The backend owns:

1. Authorization and tenant isolation.
2. Media malware scanning, checksum validation, and image resizing.
3. AI job queuing and model routing (Qwen2.5-VL-3B as an evaluation candidate).
4. Schema validation and storage of an evidence-linked AI suggestion.
5. Audit logging and enforcement of human approval before a report item is finalized.

The server response should be a structured review candidate, for example:

```json
{
  "suggestionId": "uuid",
  "categoryCandidate": "roofing",
  "componentCandidate": "asphalt_shingles",
  "visibleIndicatorCandidates": ["possible_damaged_surface_material"],
  "evidence": [
    {
      "mediaAssetId": "uuid",
      "marker": { "x": 0.41, "y": 0.23, "width": 0.12, "height": 0.09 }
    }
  ],
  "draftCaption": "Roof surface at rear slope.",
  "draftObservation": "Possible surface damage is visible.",
  "confidence": 0.71,
  "uncertaintyReason": "A photo cannot establish active leakage or repair scope.",
  "requiresHumanReview": true
}
```

The UI must present Accept, Edit, Reject, and Needs Verification actions. It must not
publish, email, or deliver a report.

## Validation

```powershell
npx tsc --noEmit
npx expo export --platform web
```

The wider product safety requirements are in the workspace document
[`production-ai-safety-requirements.txt`](../production-ai-safety-requirements.txt).
