import { useEffect, useRef, useState } from 'react'
import { ArrowDown, ArrowRight, Building2, CalendarDays, Check, CheckCircle2, ChevronRight, ClipboardList, Copy, House, ImagePlus, Images, LoaderCircle, LogIn, LogOut, MapPin, Plus, RefreshCw, Search, Users, X } from 'lucide-react'
import { address, list, request, uploadPhoto } from './api'
import type { Client, Inspection, Media, Property } from './api'
import RecordDialog from './RecordDialog'
import ReportWorkspace, { EvidencePhoto } from './ReportWorkspace'
import { signIn, signOut } from './auth'
import './workspace.css'

export type View = 'inspections' | 'clients' | 'properties'
type Row = Inspection | Client | Property
type Scope = { type: 'client' | 'property'; id: string; label: string }
const titles = { inspections: 'Inspections', clients: 'Clients', properties: 'Properties' }
const icons = { inspections: ClipboardList, clients: Users, properties: Building2 }
const categories = ['roofing', 'exterior', 'structure', 'electrical', 'heating', 'cooling', 'insulation', 'plumbing', 'interior']
const PAGE_SIZE = 20
const errorText = (error: unknown) => error instanceof Error ? error.message : 'Something went wrong. Please try again.'
const readable = (value: string) => value.replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase())
const date = (value: string | null) => value ? new Date(value).toLocaleDateString('en-CA', { month: 'short', day: 'numeric', year: 'numeric' }) : 'Not scheduled'

function App({ onDevelopmentSignOut }: { onDevelopmentSignOut?: () => void }) {
  const [view, setView] = useState<View>('inspections')
  const [storedRows, setRows] = useState<Row[]>([])
  const [clients, setClients] = useState<Client[]>([])
  const [properties, setProperties] = useState<Property[]>([])
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [scope, setScope] = useState<Scope | null>(null)
  const [revision, setRevision] = useState(0)
  const [loadedRequest, setLoadedRequest] = useState('')
  const [loadingMore, setLoadingMore] = useState(false)
  const [canLoadMore, setHasMore] = useState(false)
  const [error, setError] = useState('')
  const [connected, setConnected] = useState(false)
  const [dialog, setDialog] = useState<View | null>(null)
  const [toast, setToast] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [storedDetail, setDetail] = useState<{ inspection: Inspection; client: Client | null; media: Media[] } | null>(null)
  const [loadedDetail, setLoadedDetail] = useState('')
  const [detailError, setDetailError] = useState('')
  const [detailRevision, setDetailRevision] = useState(0)
  const [mediaHasMore, setMediaHasMore] = useState(false)
  const [mediaLoading, setMediaLoading] = useState(false)
  const [category, setCategory] = useState('')
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState('')
  const [previews, setPreviews] = useState<Record<string, string>>({})
  const previewUrls = useRef<string[]>([])
  const fileInput = useRef<HTMLInputElement>(null)
  const requestGeneration = useRef(0)
  const detailGeneration = useRef(0)
  const [today] = useState(() => new Date().toLocaleDateString('en-CA', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }))

  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 350)
    return () => clearTimeout(timer)
  }, [search])
  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(''), 6000)
    return () => clearTimeout(timer)
  }, [toast])
  useEffect(() => () => previewUrls.current.forEach((url) => URL.revokeObjectURL(url)), [])
  useEffect(() => {
    const controller = new AbortController()
    Promise.all([list<Client>('/v1/clients', controller.signal, undefined, 100), list<Property>('/v1/properties', controller.signal, undefined, 100)])
      .then(([nextClients, nextProperties]) => { setClients(nextClients); setProperties(nextProperties) })
      .catch((failure) => { if (!controller.signal.aborted) setError(errorText(failure)) })
    return () => controller.abort()
  }, [revision])

  const path = view === 'inspections' && scope ? `/v1/${scope.type === 'client' ? 'clients' : 'properties'}/${scope.id}/inspections`
    : view === 'properties' && query.length >= 3 ? `/v1/properties?search=${encodeURIComponent(query)}` : `/v1/${view}`
  const requestKey = `${path}:${revision}:${view}:${query}`
  const shortSearch = view === 'properties' && query.length > 0 && query.length < 3
  const loading = loadedRequest !== requestKey && !shortSearch
  const rows = loadedRequest === requestKey && !shortSearch ? storedRows : []
  const hasMore = loadedRequest === requestKey && canLoadMore
  const detailKey = selectedId ? `${selectedId}:${detailRevision}` : ''
  const detail = loadedDetail === detailKey ? storedDetail : null
  const detailLoading = Boolean(selectedId) && loadedDetail !== detailKey
  const visibleDetailError = loadedDetail === detailKey ? detailError : ''

  useEffect(() => {
    const controller = new AbortController()
    requestGeneration.current += 1
    if (shortSearch) return () => controller.abort()
    list<Row>(path, controller.signal).then((nextRows) => { if (!controller.signal.aborted) { setRows(nextRows); setHasMore(nextRows.length === PAGE_SIZE); setConnected(true); setError('') } })
      .catch((failure) => { if (!controller.signal.aborted) { setRows([]); setHasMore(false); setError(errorText(failure)); setConnected(false) } })
      .finally(() => { if (!controller.signal.aborted) setLoadedRequest(requestKey) })
    return () => controller.abort()
  }, [path, requestKey, shortSearch])

  useEffect(() => {
    detailGeneration.current += 1
    if (!selectedId) return
    const controller = new AbortController()
    request<Inspection>(`/v1/inspections/${selectedId}`, { signal: controller.signal }).then(async (inspection) => {
      const [media, customer] = await Promise.all([
        list<Media>(`/v1/inspections/${selectedId}/media`, controller.signal),
        inspection.client_id ? request<Client>(`/v1/clients/${inspection.client_id}`, { signal: controller.signal }) : Promise.resolve(null),
      ])
      if (!controller.signal.aborted) { setDetail({ inspection, client: customer, media }); setMediaHasMore(media.length === PAGE_SIZE); setDetailError('') }
    }).catch((failure) => { if (!controller.signal.aborted) { setDetail(null); setDetailError(errorText(failure)) } })
      .finally(() => { if (!controller.signal.aborted) setLoadedDetail(detailKey) })
    return () => controller.abort()
  }, [selectedId, detailKey])

  function navigate(next: View) { setView(next); setSearch(''); setQuery(''); setScope(null); setSelectedId(null) }
  async function loadMore() {
    if (loadingMore || !rows.length) return
    const generation = requestGeneration.current
    setLoadingMore(true)
    try {
      const page = await list<Row>(path, undefined, rows.at(-1)!.id)
      if (generation === requestGeneration.current) { setRows((current) => [...current, ...page]); setHasMore(page.length === PAGE_SIZE) }
    } catch (failure) { if (generation === requestGeneration.current) setError(errorText(failure)) }
    finally { setLoadingMore(false) }
  }
  async function loadMedia() {
    if (!detail || mediaLoading) return
    const inspectionId = detail.inspection.id
    const generation = detailGeneration.current
    setMediaLoading(true)
    try {
      const page = await list<Media>(`/v1/inspections/${inspectionId}/media`, undefined, detail.media.at(-1)?.id)
      if (generation !== detailGeneration.current) return
      setDetail((current) => current?.inspection.id === inspectionId ? { ...current, media: [...current.media, ...page] } : current)
      setMediaHasMore(page.length === PAGE_SIZE)
    } catch (failure) { if (generation === detailGeneration.current) setDetailError(errorText(failure)) }
    finally { setMediaLoading(false) }
  }
  async function addPhotos(files: FileList | null) {
    if (!files?.length || !detail || uploading) return
    if (files.length > 10) { setDetailError('Choose up to 10 photos per batch.'); return }
    const inspectionId = detail.inspection.id
    setUploading(true); setDetailError('')
    let completed = 0
    try {
      for (const file of Array.from(files)) {
        setUploadProgress(`Uploading ${completed + 1} of ${files.length}`)
        const mediaId = await uploadPhoto(inspectionId, file, category)
        const preview = URL.createObjectURL(file)
        previewUrls.current.push(preview)
        setPreviews((current) => ({ ...current, [mediaId]: preview }))
        completed += 1
      }
      setToast(`${completed} photo${completed === 1 ? '' : 's'} uploaded`)
    } catch (failure) { setDetailError(`${completed} uploaded. ${errorText(failure)}`) }
    finally { setUploading(false); setUploadProgress(''); setDetailRevision((value) => value + 1); if (fileInput.current) fileInput.current.value = '' }
  }
  async function copy(value: string) {
    try { await navigator.clipboard.writeText(value); setToast('ID copied') }
    catch { setError('Clipboard access is unavailable in this browser.') }
  }
  function related(type: Scope['type'], id: string, label: string) { setScope({ type, id, label }); setView('inspections'); setSearch(''); setQuery(''); setSelectedId(null) }

  const shownRows = view === 'properties' || !query ? rows : rows.filter((row) => {
    const text = 'full_name' in row ? `${row.full_name} ${row.email ?? ''} ${row.id}` : 'property_address' in row ? `${row.property_address ?? ''} ${row.id} ${clients.find((customer) => customer.id === row.client_id)?.full_name ?? ''}` : address(row)
    return text.toLowerCase().includes(query.toLowerCase())
  })
  const PageIcon = icons[view]

  return <div className="app-shell">
    <header className="workspace-nav">
      <a href="/" className="brand" aria-label="Habitat home"><span className="brand-mark"><House size={24} /></span><span>habitat<span className="brand-sub">INSPECTION WORKSPACE</span></span></a>
      <nav aria-label="Workspace navigation">{(Object.keys(titles) as View[]).map((item) => { const Icon = icons[item]; return <button key={item} aria-current={view === item ? 'page' : undefined} onClick={() => navigate(item)}><Icon size={18} /><span>{titles[item]}</span></button> })}</nav>
      <div className="nav-account"><span className="avatar" aria-hidden="true">IW</span><span className="account-label"><strong>Inspector workspace</strong><small>{import.meta.env.DEV ? 'Development' : 'Company account'}</small></span>{import.meta.env.DEV ? <button className="nav-signin" type="button" onClick={onDevelopmentSignOut}><LogOut size={16} />Sign out</button> : <div className="auth-actions"><button className="icon-button" title="Renew sign-in" aria-label="Renew sign-in" onClick={() => void signIn().then(() => setRevision((value) => value + 1)).catch((failure) => setError(errorText(failure)))}><LogIn size={18} /></button><button className="icon-button" title="Sign out" aria-label="Sign out" onClick={() => void signOut().catch((failure) => setError(errorText(failure)))}><LogOut size={18} /></button></div>}</div>
    </header>
    <div className="main-shell">
      <header className="topbar"><div className="breadcrumb">Workspace<ChevronRight size={14} /><strong>{titles[view]}</strong></div><div className="topbar-status"><span className={connected ? 'connection-dot connected' : 'connection-dot'} />{connected ? 'API connected' : 'API unavailable'}<span className="local-label">{import.meta.env.DEV ? 'LOCAL' : 'DEPLOYED'}</span></div></header>
      <main className="workspace-content">
        <div className="page-heading"><div><div className="eyebrow">FIELD OPERATIONS</div><h1>{titles[view]}</h1><p>{today}</p></div><div className="heading-actions"><button className="icon-button" title="Refresh records" aria-label="Refresh records" disabled={loading} onClick={() => { setRevision((value) => value + 1); setDetailRevision((value) => value + 1) }}><RefreshCw size={18} className={loading ? 'spinning' : ''} /></button><button className="primary-button" onClick={() => setDialog(view)}><Plus size={18} />New {view === 'properties' ? 'property' : view === 'clients' ? 'client' : 'inspection'}</button></div></div>
        {error && <div className="error-banner" role="alert"><span>{error}</span><button onClick={() => setRevision((value) => value + 1)}>Retry</button></div>}
        <div className="directory-layout">
          <section className="directory" aria-label={titles[view]}>
            <div className="directory-toolbar"><label className="search-field"><Search size={18} /><input type="search" aria-label={`Search ${titles[view].toLowerCase()}`} placeholder={view === 'properties' ? 'Search property addresses' : view === 'clients' ? 'Name, email or UUID on this page' : 'Address, client or UUID on this page'} value={search} onChange={(event) => setSearch(event.target.value)} /></label><span className="record-count">{rows.length}{hasMore ? '+' : ''} loaded</span></div>
            {scope && <div className="scope-bar"><MapPin size={15} /><span>{scope.label}</span><button className="icon-button small" aria-label="Clear inspection filter" title="Clear inspection filter" onClick={() => setScope(null)}><X size={15} /></button></div>}
            <div className="table-wrap" aria-busy={loading}><table><thead><tr><th>{view === 'inspections' ? 'PROPERTY / CLIENT' : view === 'clients' ? 'CLIENT' : 'PROPERTY'}</th><th className="secondary-column">{view === 'inspections' ? 'SCHEDULE' : view === 'clients' ? 'EMAIL' : 'LOCATION'}</th><th>{view === 'inspections' ? 'STATUS' : 'RECORD'}</th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>{!loading && shownRows.map((row) => {
              if (view === 'inspections') { const inspection = row as Inspection; return <tr key={row.id} className={selectedId === row.id ? 'selected-row' : ''}><td><button className="row-title" disabled={uploading} onClick={() => setSelectedId(row.id)}><span className="row-icon"><House size={18} /></span><span><strong>{inspection.property_address || 'Property address unavailable'}</strong><small>{clients.find((customer) => customer.id === inspection.client_id)?.full_name ?? 'Client record'}<span className="row-reference">#{row.id.slice(0, 8)}</span></small></span></button></td><td className="secondary-column"><span className="date-cell"><CalendarDays size={14} />{date(inspection.scheduled_for)}</span></td><td><span className={`status-badge ${inspection.status}`}>{readable(inspection.status)}</span></td><td><button className="icon-button" aria-label={`Open inspection ${row.id.slice(0, 8)}`} title="Open inspection" disabled={uploading} onClick={() => setSelectedId(row.id)}><ArrowRight size={17} /></button></td></tr> }
              if (view === 'clients') { const customer = row as Client; return <tr key={row.id}><td><button className="row-title" onClick={() => related('client', row.id, customer.full_name)}><span className="row-icon client-icon"><Users size={18} /></span><span><strong>{customer.full_name}</strong><small>Client</small></span></button></td><td className="secondary-column">{customer.email || <span className="muted">Not provided</span>}</td><td><span className="uuid">{row.id.slice(0, 8)}</span></td><td><button className="icon-button" aria-label={`Copy client ID for ${customer.full_name}`} title="Copy client UUID" onClick={() => void copy(row.id)}><Copy size={16} /></button></td></tr> }
              const property = row as Property; return <tr key={row.id}><td><button className="row-title" onClick={() => related('property', row.id, address(property))}><span className="row-icon property-icon"><Building2 size={18} /></span><span><strong>{property.address_line1}{property.address_line2 ? `, ${property.address_line2}` : ''}</strong><small>{property.postal_code} / {property.country}</small></span></button></td><td className="secondary-column">{property.city}, {property.region}</td><td><span className="uuid">{row.id.slice(0, 8)}</span></td><td><button className="icon-button" aria-label={`Copy property ID for ${property.address_line1}`} title="Copy property UUID" onClick={() => void copy(row.id)}><Copy size={16} /></button></td></tr>
            })}</tbody></table>
              {loading ? <div className="empty-state"><LoaderCircle className="spinning" size={25} /><h3>Loading {titles[view].toLowerCase()}</h3></div> : shownRows.length === 0 && <div className="empty-state"><PageIcon size={30} /><h3>{query ? 'No matching records' : `No ${titles[view].toLowerCase()} yet`}</h3>{view === 'properties' && query.length > 0 && query.length < 3 ? <p>Enter at least 3 characters.</p> : !query && <button className="text-button" onClick={() => setDialog(view)}><Plus size={16} />Create {view === 'properties' ? 'property' : view === 'clients' ? 'client' : 'inspection'}</button>}</div>}
            </div>
            <div className="table-footer"><span>{shownRows.length} {shownRows.length === 1 ? 'record' : 'records'} shown</span>{hasMore && <button className="text-button" disabled={loadingMore} onClick={() => void loadMore()}>{loadingMore ? <LoaderCircle size={15} className="spinning" /> : <ArrowDown size={15} />}Load more</button>}</div>
          </section>
          {view === 'inspections' && selectedId && <aside className="inspection-panel" aria-label="Inspection details"><div className="panel-heading"><span>INSPECTION DETAILS</span>{selectedId && <button className="icon-button small" aria-label="Close inspection details" title="Close inspection details" disabled={uploading} onClick={() => setSelectedId(null)}><X size={17} /></button>}</div>
            {detailLoading ? <div className="empty-state"><LoaderCircle size={25} className="spinning" /><h3>Loading inspection</h3></div> : detail ? <>
              <div className="inspection-address"><span className={`status-badge ${detail.inspection.status}`}>{readable(detail.inspection.status)}</span><h2>{detail.inspection.property_address}</h2><div className="detail-client"><Users size={16} /><span>{detail.client?.full_name ?? 'No client linked'}</span></div><div className="detail-client"><CalendarDays size={16} /><span>{date(detail.inspection.scheduled_for)}</span></div><button className="id-button" title="Copy inspection UUID" onClick={() => void copy(detail.inspection.id)}>#{detail.inspection.id.slice(0, 8)}<Copy size={13} /></button></div>
              <div className="evidence-heading"><h3>Photo evidence <span>{detail.media.length}{mediaHasMore ? '+' : ''}</span></h3><Images size={17} /></div>
              <div className="upload-controls"><label className="sr-only" htmlFor="photo-category">Photo category</label><select id="photo-category" value={category} disabled={uploading} onChange={(event) => setCategory(event.target.value)}><option value="">Uncategorized</option>{categories.map((item) => <option key={item} value={item}>{readable(item)}</option>)}</select><button className="secondary-button" disabled={uploading} onClick={() => fileInput.current?.click()}>{uploading ? <LoaderCircle size={16} className="spinning" /> : <ImagePlus size={16} />}{uploading ? 'Uploading' : 'Add photos'}</button><input ref={fileInput} className="sr-only" type="file" aria-label="Upload inspection photos" accept="image/jpeg,image/png,image/webp" multiple disabled={uploading} onChange={(event) => void addPhotos(event.target.files)} /></div>
              {uploadProgress && <div className="upload-progress" role="status">{uploadProgress}</div>}
              {!detail.media.length ? <div className="empty-state evidence-empty"><Images size={30} /><h3>No photos attached</h3></div> : <div className="evidence-list">{detail.media.map((media, index) => <figure key={media.id} className="evidence-item">{previews[media.id] ? <a href={previews[media.id]} target="_blank" rel="noreferrer" title={`Open original ${media.file_name}`}><img src={previews[media.id]} alt={media.file_name} loading="lazy" /></a> : <EvidencePhoto key={media.id} media={media} />}<figcaption><div><span className="photo-number">{String(index + 1).padStart(2, '0')}</span><strong>{media.file_name}</strong></div><span className="media-meta">{media.requested_category ? readable(media.requested_category) : 'Uncategorized'} / {(media.content_length / 1024).toFixed(0)} KB</span><span className="media-state"><CheckCircle2 size={13} />{readable(media.processing_state)}</span></figcaption></figure>)}</div>}
              {mediaHasMore && <button className="text-button media-more" disabled={mediaLoading} onClick={() => void loadMedia()}><ArrowDown size={15} />{mediaLoading ? 'Loading photos' : 'Load more photos'}</button>}
            </> : !visibleDetailError && <div className="empty-state panel-empty"><span className="selection-icon"><ClipboardList size={30} /></span><h3>No inspection selected</h3></div>}
            {visibleDetailError && <div className="error-banner panel-error" role="alert"><span>{visibleDetailError}</span><button onClick={() => setDetailRevision((value) => value + 1)}>Retry</button></div>}
          </aside>}
        </div>
        {view === 'inspections' && detail && <ReportWorkspace key={detail.inspection.id} inspection={detail.inspection} media={detail.media} mediaHasMore={mediaHasMore} />}
        <footer className="page-footer"><span><Check size={14} />Private workspace / human-reviewed findings</span><span>Habitat / {import.meta.env.DEV ? 'Development' : 'Inspector workspace'}</span></footer>
      </main>
    </div>
    {dialog && <RecordDialog mode={dialog} clients={clients} properties={properties} onClose={() => setDialog(null)} onMoreClients={async () => { const page = await list<Client>('/v1/clients', undefined, clients.at(-1)?.id, 100); setClients((current) => [...current, ...page]); return page.length === 100 }} onMoreProperties={async () => { const page = await list<Property>('/v1/properties', undefined, properties.at(-1)?.id, 100); setProperties((current) => [...current, ...page]); return page.length === 100 }} onSaved={(row) => { const savedMode = dialog; setDialog(null); setRevision((value) => value + 1); setSearch(''); setQuery(''); setScope(null); setView(savedMode); if (savedMode === 'inspections') setSelectedId(row.id); setToast(`${savedMode === 'inspections' ? 'Inspection' : savedMode === 'clients' ? 'Client' : 'Property'} created`) }} />}
    {toast && <div className="toast" role="status"><CheckCircle2 size={18} /><span>{toast}</span><button className="icon-button small" aria-label="Dismiss notification" onClick={() => setToast('')}><X size={15} /></button></div>}
  </div>
}

export default App
