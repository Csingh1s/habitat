import { authorizationHeaders } from './auth'

export interface Client {
  id: string
  full_name: string
  email: string | null
}

export interface Property {
  id: string
  address_line1: string
  address_line2: string
  city: string
  region: string
  postal_code: string
  country: 'CA' | 'US'
}

export interface Inspection {
  id: string
  client_id: string | null
  property_id: string | null
  property_address: string | null
  scheduled_for: string | null
  status: string
  service_template_version: string
}

export interface Media {
  id: string
  inspection_id: string
  file_name: string
  content_type: string
  content_length: number
  capture_timestamp: string
  requested_category: string | null
  processing_state: string
  inspector_note?: string
}

export type ClientInput = Omit<Client, 'id'>
export type PropertyInput = Omit<Property, 'id'>
export interface InspectionInput {
  client_id: string
  property_id: string
  scheduled_for: string | null
}

export function address(property: Property): string {
  return [property.address_line1, property.address_line2, property.city, property.region, property.postal_code, property.country].filter(Boolean).join(', ')
}

function errorMessage(body: unknown, fallback: string): string {
  if (!body || typeof body !== 'object' || !('detail' in body)) return fallback
  if (typeof body.detail === 'string') return body.detail
  if (Array.isArray(body.detail)) return body.detail.map((item) => item.msg ?? 'Invalid input').join('; ')
  return fallback
}

export async function requestResponse(path: string, init: RequestInit = {}, timeoutMs = 15_000): Promise<Response> {
  const headers = new Headers(init.headers)
  for (const [name, value] of Object.entries(await authorizationHeaders())) headers.set(name, value)
  if (init.body) headers.set('Content-Type', 'application/json')
  const base = import.meta.env.DEV ? '/api' : ((import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? '')
  if (!import.meta.env.DEV && base && !base.startsWith('https://')) throw new Error('The deployed API URL must use HTTPS.')
  let response: Response
  try {
    response = await fetch(`${base}${path}`, {
      ...init, headers,
      signal: init.signal ? AbortSignal.any([init.signal, AbortSignal.timeout(timeoutMs)]) : AbortSignal.timeout(timeoutMs),
    })
  } catch (error) {
    if (init.signal?.aborted) throw error
    throw new Error(import.meta.env.DEV ? 'The local API could not be reached. Check the API on port 8001 and try again.' : 'The API could not be reached. Check your connection and retry.')
  }
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    throw new Error(errorMessage(body, `API request failed (${response.status}).`))
  }
  return response
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await requestResponse(path, init)
  const body: unknown = await response.json().catch(() => null)
  if (body === null) throw new Error('The API returned an unexpected response.')
  return body as T
}

export function list<T>(path: string, signal?: AbortSignal, after?: string, limit = 20): Promise<T[]> {
  const url = new URL(path, 'http://local.invalid')
  url.searchParams.set('limit', String(limit))
  if (after) url.searchParams.set('after', after)
  return request<T[]>(`${url.pathname}${url.search}`, { signal })
}

export function create<T>(path: string, payload: unknown, key: string): Promise<T> {
  return request<T>(path, { method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify(payload) })
}

export async function uploadPhoto(inspectionId: string, file: File, category: string): Promise<string> {
  const contentType = file.type || ({ jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', webp: 'image/webp' }[file.name.split('.').pop()?.toLowerCase() ?? ''])
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(contentType ?? '')) throw new Error(`${file.name}: select a JPEG, PNG, or WebP image.`)
  if (file.size === 0 || file.size > 25_000_000) throw new Error(`${file.name}: images must be between 1 byte and 25 MB.`)
  const bytes = await file.arrayBuffer()
  const checksum = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), (byte) => byte.toString(16).padStart(2, '0')).join('')
  const intent = await create<{ media_asset_id: string; upload_url: string; required_headers: Record<string, string>; storage_etag?: string | null }>(
    `/v1/inspections/${inspectionId}/media/upload-intents`, {
      file_name: file.name, content_type: contentType, content_length: file.size,
      checksum_sha256: checksum, capture_timestamp: new Date(file.lastModified).toISOString(),
      requested_category: category || null,
    }, `web-upload-${inspectionId}-${checksum}`,
  )
  const uploadUrl = new URL(intent.upload_url)
  if (import.meta.env.DEV && (!['localhost', '127.0.0.1'].includes(uploadUrl.hostname) || !uploadUrl.pathname.startsWith('/development/uploads/'))) {
    throw new Error('This local workspace only accepts the development upload destination.')
  }
  if (!import.meta.env.DEV && uploadUrl.protocol !== 'https:') throw new Error('The upload destination must use HTTPS.')
  let storageEtag = intent.storage_etag
  if (!storageEtag) {
    const uploaded = await fetch(import.meta.env.DEV ? `/api${uploadUrl.pathname}` : uploadUrl.toString(), {
      method: 'PUT', body: bytes, signal: AbortSignal.timeout(60_000),
      headers: { ...intent.required_headers, 'Content-Type': contentType!, 'X-Checksum-Sha256': checksum },
    })
    if (!uploaded.ok) throw new Error(`Photo storage failed (${uploaded.status}). You can retry the same file.`)
    storageEtag = import.meta.env.DEV ? 'development-etag' : uploaded.headers.get('etag')?.replaceAll('"', '')
  }
  if (!storageEtag) throw new Error('Storage confirmation requires an ETag from the upload provider.')
  await create(`/v1/media/${intent.media_asset_id}/complete`, {
    checksum_sha256: checksum, storage_etag: storageEtag,
  }, `web-complete-${intent.media_asset_id}-${checksum}`)
  return intent.media_asset_id
}