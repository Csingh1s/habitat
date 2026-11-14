import * as Crypto from 'expo-crypto';
import { File, UploadType } from 'expo-file-system';
import { Platform } from 'react-native';

export type InspectionCategory =
  | 'roofing'
  | 'exterior'
  | 'structure'
  | 'electrical'
  | 'heating'
  | 'cooling'
  | 'insulation'
  | 'plumbing'
  | 'interior';

export type AnalysisStatus = 'queued' | 'running' | 'succeeded' | 'blocked' | 'failed';

export type ReviewCandidate = {
  id: string;
  media_asset_id: string;
  model_id: string;
  model_version: string;
  category_candidate: InspectionCategory | null;
  component_candidate: string | null;
  visible_indicator_candidates: string[];
  evidence_marker: {
    x: number;
    y: number;
    width: number;
    height: number;
    label: string;
  } | null;
  draft_caption: string;
  draft_observation: string | null;
  confidence: number;
  uncertainty_reason: string;
  requires_human_review: true;
};

export type AnalysisJob = {
  id: string;
  media_asset_id: string;
  status: AnalysisStatus;
  model_id: string;
  model_version: string;
  review_candidate: ReviewCandidate | null;
  error_message: string | null;
};

export type Inspection = {
  id: string;
  client_id: string | null;
  property_id: string | null;
  status: string;
  service_template_version: string;
  scheduled_for: string | null;
  property_address: string | null;
  assigned_inspector_id: string | null;
};

export type OnboardingProfile = {
  user_id: string;
  tenant_id: string;
  full_name: string;
  email: string | null;
  role: string;
  country: string | null;
  region: string | null;
};

type UploadIntent = {
  media_asset_id: string;
  upload_url: string;
  required_headers: Record<string, string>;
  storage_etag?: string | null;
};

type UploadCompletion = {
  media_asset_id: string;
  processing_state: string;
};

export type CapturedEvidence = {
  uri: string;
  fileName: string;
  contentType: 'image/jpeg' | 'image/png' | 'image/webp';
  captureTimestamp: string;
  inspectorNote?: string;
};

type ApiMode = 'development' | 'deployed';

type AuthenticatedApiSession = {
  accessToken: string;
  inspectionId: string;
};

const apiBaseUrl = process.env.EXPO_PUBLIC_HABITAT_API_BASE_URL?.replace(/\/$/, '');
const apiMode = process.env.EXPO_PUBLIC_HABITAT_API_MODE as ApiMode | undefined;
let authenticatedSession: AuthenticatedApiSession | null = null;
let selectedInspectionId: string | null = null;

export class HabitatApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = 'HabitatApiError';
  }
}

export function configureAuthenticatedApiSession(session: AuthenticatedApiSession | null): void {
  authenticatedSession = session;
  selectedInspectionId = session?.inspectionId || null;
}

export function selectInspectionForCapture(inspectionId: string): void {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(inspectionId)) {
    throw new HabitatApiError('Select a valid assigned inspection before capturing evidence.');
  }
  selectedInspectionId = inspectionId;
}

export async function onboardWorkspace(
  accessToken: string,
  payload: { companyName: string; fullName: string; country: string; region: string },
): Promise<OnboardingProfile> {
  configureAuthenticatedApiSession({ accessToken, inspectionId: '' });
  return request<OnboardingProfile>('/v1/onboarding', {
    method: 'POST',
    body: JSON.stringify({
      company_name: payload.companyName,
      full_name: payload.fullName,
      country: payload.country,
      region: payload.region,
    }),
  });
}

export async function fetchAssignedInspections(accessToken?: string, after?: string): Promise<Inspection[]> {
  if (accessToken && accessToken !== authenticatedSession?.accessToken) {
    configureAuthenticatedApiSession({ accessToken, inspectionId: '' });
  }
  return request<Inspection[]>(`/v1/inspections?limit=50${after ? `&after=${encodeURIComponent(after)}` : ''}`);
}

function requestHeaders(): Record<string, string> {
  if (apiMode === 'development') {
    return {
      'X-Dev-Tenant-Id': 'demo-tenant',
      'X-Dev-User-Id': 'demo-inspector',
    };
  }

  if (apiMode === 'deployed' && authenticatedSession) {
    return { Authorization: `Bearer ${authenticatedSession.accessToken}` };
  }

  throw new HabitatApiError(
    'Sign in before uploading evidence. The deployed API requires a user access token.',
  );
}

function requireApiBaseUrl(): string {
  if (!apiBaseUrl) {
    throw new HabitatApiError(
      'Set EXPO_PUBLIC_HABITAT_API_BASE_URL before uploading inspection evidence.',
    );
  }
  if (apiMode !== 'development' && apiMode !== 'deployed') {
    throw new HabitatApiError(
      'Set EXPO_PUBLIC_HABITAT_API_MODE to development or deployed.',
    );
  }
  return apiBaseUrl;
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  requiresIdempotencyKey = false,
): Promise<T> {
  const headers = new Headers(options.headers);
  for (const [name, value] of Object.entries(requestHeaders())) {
    headers.set(name, value);
  }
  if (requiresIdempotencyKey) {
    if (!headers.has('Idempotency-Key')) headers.set('Idempotency-Key', Crypto.randomUUID());
  }
  if (options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  let response: Response;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15_000);
  try {
    response = await fetch(`${requireApiBaseUrl()}${path}`, { ...options, headers, signal: controller.signal });
  } catch {
    throw new HabitatApiError(
      'Could not reach the API. Check the environment API URL and connection.',
    );
  } finally {
    clearTimeout(timeout);
  }

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = typeof payload?.detail === 'string' ? payload.detail : `Request failed (${response.status}).`;
    throw new HabitatApiError(detail, response.status);
  }

  return response.json() as Promise<T>;
}

function resolveUploadUrl(uploadUrl: string): string {
  const configuredUrl = new URL(requireApiBaseUrl());
  const uploadTarget = new URL(uploadUrl);
  if (
    apiMode === 'development'
    && (uploadTarget.hostname === 'localhost' || uploadTarget.hostname === '127.0.0.1')
  ) {
    uploadTarget.protocol = configuredUrl.protocol;
    uploadTarget.host = configuredUrl.host;
  }
  return uploadTarget.toString();
}

function hexDigest(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

async function sha256(file: Blob): Promise<string> {
  const digest = await Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256, await file.arrayBuffer());
  return hexDigest(digest);
}

async function uploadFile(
  file: File | Blob,
  uploadUrl: string,
  contentType: CapturedEvidence['contentType'],
  headers: Record<string, string>,
): Promise<string | null> {
  const responseHeaders = { ...headers, 'Content-Type': contentType };
  if (Platform.OS === 'web') {
    const response = await fetch(uploadUrl, {
      method: 'PUT',
      headers: responseHeaders,
      body: file,
    });
    if (!response.ok) {
      throw new HabitatApiError(`Image upload failed (${response.status}).`, response.status);
    }
    return response.headers.get('etag');
  }

  if (!(file instanceof File)) throw new HabitatApiError('Native evidence file is unavailable.');
  const result = await file.upload(uploadUrl, {
    httpMethod: 'PUT',
    uploadType: UploadType.BINARY_CONTENT,
    headers: responseHeaders,
    mimeType: contentType,
  });
  if (result.status < 200 || result.status >= 300) {
    throw new HabitatApiError(`Image upload failed (${result.status}).`, result.status);
  }
  const etagHeader = Object.entries(result.headers).find(
    ([name]) => name.toLowerCase() === 'etag',
  );
  return etagHeader?.[1] ?? null;
}

async function getTargetInspectionId(): Promise<string> {
  if (!selectedInspectionId) throw new HabitatApiError('Select an inspection before uploading evidence.');
  return selectedInspectionId;
}

async function waitForAnalysis(analysisId: string): Promise<AnalysisJob> {
  const maximumPolls = 20;
  for (let poll = 0; poll < maximumPolls; poll += 1) {
    const job = await request<AnalysisJob>(`/v1/analyses/${analysisId}`);
    if (job.status === 'succeeded' || job.status === 'blocked' || job.status === 'failed') {
      return job;
    }
    await new Promise((resolve) => setTimeout(resolve, 750));
  }
  throw new HabitatApiError('Analysis is still running. Check the job again from the inspection evidence list.');
}

export async function submitEvidenceForAnalysis(
  evidence: CapturedEvidence,
  requestedCategory: InspectionCategory,
  onProgress: (phase: 'uploading' | 'validating' | 'analyzing') => void,
  analysisAttemptId?: string,
): Promise<AnalysisJob> {
  const inspectionId = await getTargetInspectionId();
  const file = Platform.OS === 'web'
    ? await fetch(evidence.uri).then((response) => {
      if (!response.ok) throw new HabitatApiError('The selected photo cannot be read. Select it again.');
      return response.blob();
    })
    : new File(evidence.uri);
  if (file.size <= 0 || file.size > 25_000_000) {
    throw new HabitatApiError('Choose an image between 1 byte and 25 MB.');
  }

  onProgress('uploading');
  const checksumSha256 = await sha256(file);
  const intent = await request<UploadIntent>(
    `/v1/inspections/${inspectionId}/media/upload-intents`,
    {
      method: 'POST',
      headers: { 'Idempotency-Key': `mobile-upload-${inspectionId}-${checksumSha256}` },
      body: JSON.stringify({
        file_name: evidence.fileName,
        content_type: evidence.contentType,
        content_length: file.size,
        checksum_sha256: checksumSha256,
        capture_timestamp: evidence.captureTimestamp,
        requested_category: requestedCategory,
        inspector_note: evidence.inspectorNote ?? '',
      }),
    },
    true,
  );

  const developmentStorageEtag = `mobile-${checksumSha256}`;
  const providerEtag = intent.storage_etag ?? await uploadFile(file, resolveUploadUrl(intent.upload_url), evidence.contentType, {
    ...intent.required_headers,
    'X-Checksum-Sha256': checksumSha256,
    ...(apiMode === 'development' ? { 'X-Storage-ETag': developmentStorageEtag } : {}),
  });
  const storageEtag = intent.storage_etag ?? (apiMode === 'development' ? developmentStorageEtag : providerEtag?.replaceAll('"', ''));
  if (!storageEtag) {
    throw new HabitatApiError(
      'The storage service did not return an ETag. Upload confirmation cannot continue safely.',
    );
  }

  onProgress('validating');
  await request<UploadCompletion>(
    `/v1/media/${intent.media_asset_id}/complete`,
    {
      method: 'POST',
      headers: { 'Idempotency-Key': `mobile-complete-${intent.media_asset_id}-${checksumSha256}` },
      body: JSON.stringify({
        storage_etag: storageEtag,
        checksum_sha256: checksumSha256,
      }),
    },
    true,
  );

  onProgress('analyzing');
  const analysis = await request<AnalysisJob>(
    `/v1/media/${intent.media_asset_id}/analyses`,
    {
      method: 'POST',
      headers: { 'Idempotency-Key': `mobile-analysis-${intent.media_asset_id}${analysisAttemptId ? `-${analysisAttemptId}` : ''}` },
      body: JSON.stringify({ requested_category: requestedCategory }),
    },
    true,
  );
  return waitForAnalysis(analysis.id);
}
