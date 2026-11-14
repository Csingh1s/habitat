import { afterEach, describe, expect, it, vi } from 'vitest'
import { address, create, list, request, requestResponse, uploadPhoto } from './api'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe('directory API contract', () => {
  it('allows a bounded PDF timeout without extending ordinary requests', async () => {
    const timeout = vi.spyOn(AbortSignal, 'timeout')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('%PDF-test', { headers: { 'Content-Type': 'application/pdf' } })))
    const response = await requestResponse('/v1/reports/report-id/pdf', {}, 120_000)
    expect(response.headers.get('Content-Type')).toBe('application/pdf')
    expect(timeout).toHaveBeenLastCalledWith(120_000)
    await requestResponse('/health')
    expect(timeout).toHaveBeenLastCalledWith(15_000)
  })

  it('uses the proxy without browser-side identity headers', async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json([]))
    vi.stubGlobal('fetch', fetchMock)
    await list('/v1/properties?search=Test%20Street', undefined, 'next-id')
    const [path, options] = fetchMock.mock.calls[0]
    expect(path).toBe('/api/v1/properties?search=Test+Street&limit=20&after=next-id')
    expect(options.headers.has('X-Dev-Tenant-Id')).toBe(false)
  })

  it('preserves explicit idempotency keys and JSON bodies', async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ id: 'client-id' }))
    vi.stubGlobal('fetch', fetchMock)
    await create('/v1/clients', { full_name: 'Alex' }, 'reusable-key')
    expect(fetchMock.mock.calls[0][1].headers.get('Idempotency-Key')).toBe('reusable-key')
    expect(fetchMock.mock.calls[0][1].body).toBe('{"full_name":"Alex"}')
  })

  it('surfaces actionable validation errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ detail: [{ msg: 'Name is required' }] }, { status: 422 })))
    await expect(request('/v1/clients')).rejects.toThrow('Name is required')
  })

  it('handles an unavailable local API and non-JSON responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('fetch failed')))
    await expect(request('/health')).rejects.toThrow('port 8001')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>proxy failure</html>')))
    await expect(request('/health')).rejects.toThrow('unexpected response')
  })

  it('formats structured addresses without empty units', () => {
    expect(address({ id: 'id', address_line1: '100 Test Street', address_line2: '', city: 'Toronto', region: 'ON', postal_code: 'A1A 1A1', country: 'CA' })).toBe('100 Test Street, Toronto, ON, A1A 1A1, CA')
  })

  it('rejects unsupported and empty images before creating an upload intent', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    await expect(uploadPhoto('inspection-id', new File(['text'], 'notes.txt', { type: 'text/plain' }), '')).rejects.toThrow('JPEG, PNG, or WebP')
    await expect(uploadPhoto('inspection-id', new File([], 'empty.jpg', { type: 'image/jpeg' }), '')).rejects.toThrow('25 MB')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('verifies the upload checksum through intent, storage, and completion', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(Response.json({ media_asset_id: 'media-id', upload_url: 'http://localhost:8000/development/uploads/demo/photo', required_headers: {} }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(Response.json({ media_asset_id: 'media-id', processing_state: 'validation_queued' }))
    vi.stubGlobal('fetch', fetchMock)
    const file = new File(['sample-image'], 'sample.png', { type: 'image/png', lastModified: 1_000 })
    expect(await uploadPhoto('inspection-id', file, 'exterior')).toBe('media-id')
    const intent = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(intent.checksum_sha256).toMatch(/^[a-f0-9]{64}$/)
    expect(intent.requested_category).toBe('exterior')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/development/uploads/demo/photo')
    expect(fetchMock.mock.calls[1][1].headers['X-Checksum-Sha256']).toBe(intent.checksum_sha256)
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({ checksum_sha256: intent.checksum_sha256, storage_etag: 'development-etag' })
  })

  it('does not send file bytes to an unexpected upload destination', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(Response.json({
      media_asset_id: 'media-id', upload_url: 'https://unexpected.example/development/uploads/photo', required_headers: {},
    }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(uploadPhoto('inspection-id', new File(['sample'], 'sample.png', { type: 'image/png' }), '')).rejects.toThrow('development upload destination')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('resumes an already stored photo without sending file bytes again', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(Response.json({
      media_asset_id: 'media-id', upload_url: 'http://localhost:8000/development/uploads/demo/photo', required_headers: {}, storage_etag: 'existing-etag',
    })).mockResolvedValueOnce(Response.json({ media_asset_id: 'media-id', processing_state: 'validation_queued' }))
    vi.stubGlobal('fetch', fetchMock)
    expect(await uploadPhoto('inspection-id', new File(['sample'], 'sample.png', { type: 'image/png' }), '')).toBe('media-id')
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/media/media-id/complete')
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).storage_etag).toBe('existing-etag')
  })
})