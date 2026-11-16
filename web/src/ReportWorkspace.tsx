import { useEffect, useRef, useState } from 'react'
import { ArrowDown, Check, Download, ImageOff, LoaderCircle, RefreshCw, ScanSearch } from 'lucide-react'
import { create, list, requestResponse } from './api'
import type { Inspection, Media } from './api'

type Analysis = {
  id: string; media_asset_id: string; status: string; created_at: string | null; error_message: string | null
  review_candidate: { draft_caption: string; draft_observation: string | null; category_candidate: string | null; uncertainty_reason: string } | null
}
type ReviewInput = {
  media_asset_id: string; analysis_id: string | null; decision: 'accepted' | 'rejected' | 'needs_verification'
  category: string; location: string; caption: string; observation: string
}
type Review = ReviewInput & { id: string; reviewed_at: string; reviewer_id: string }
type Report = { id: string; approved_at: string; approved_by: string; findings: Review[] }
const categories = ['roofing', 'exterior', 'structure', 'electrical', 'heating', 'cooling', 'insulation', 'plumbing', 'interior']
const failureText = (failure: unknown) => failure instanceof Error ? failure.message : 'The request could not be completed.'

export function EvidencePhoto({ media, className = '' }: { media: Media; className?: string }) {
  const [photo, setPhoto] = useState('')
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    let url = ''
    requestResponse(`/v1/media/${media.id}/content`, { signal: controller.signal }).then((response) => response.blob()).then((blob) => {
      if (controller.signal.aborted) return
      url = URL.createObjectURL(blob); setPhoto(url); setError('')
    }).catch((failure) => { if (!controller.signal.aborted) setError(failureText(failure)) })
    return () => { controller.abort(); if (url) URL.revokeObjectURL(url) }
  }, [media.id, revision])
  if (error) return <div className={`photo-error ${className}`}><ImageOff size={24} /><span>{error}</span><button className="text-button" onClick={() => setRevision((value) => value + 1)}><RefreshCw size={15} />Retry photo</button></div>
  return photo ? <img className={className} src={photo} alt={media.file_name} loading={className === 'review-original' ? 'eager' : 'lazy'} /> : <div className={`photo-loading ${className}`}><LoaderCircle className="spinning" aria-label="Loading original photograph" /></div>
}

function ReviewEditor({ media, analysis, previous, busy, save }: { media: Media; analysis: Analysis | null; previous?: Review; busy: boolean; save: (payload: ReviewInput, key: string) => Promise<void> }) {
  const candidate = analysis?.status === 'succeeded' ? analysis.review_candidate : null
  const [category, setCategory] = useState(previous?.category ?? candidate?.category_candidate ?? media.requested_category ?? '')
  const [location, setLocation] = useState(previous?.location ?? '')
  const [caption, setCaption] = useState(previous?.caption ?? candidate?.draft_caption ?? '')
  const [observation, setObservation] = useState(previous?.observation ?? media.inspector_note ?? candidate?.draft_observation ?? '')
  const [decision, setDecision] = useState<ReviewInput['decision']>(previous?.decision ?? 'needs_verification')
  const key = useRef<{ signature: string; id: string } | null>(null)
  async function submit(event: React.FormEvent) {
    event.preventDefault()
    const payload: ReviewInput = { media_asset_id: media.id, analysis_id: candidate ? analysis!.id : null,
      category, location, caption, observation, decision }
    const signature = JSON.stringify(payload)
    if (key.current?.signature !== signature) key.current = { signature, id: crypto.randomUUID() }
    await save(payload, key.current.id)
  }
  return <form className="finding-form" onSubmit={(event) => void submit(event)}>
    <div className="finding-origin"><strong>{candidate ? 'Qwen draft' : 'Inspector finding'}</strong><span>{analysis ? analysis.status : 'Not analyzed'}</span></div>
    {analysis?.error_message && <p className="review-notice" role="status">{analysis.error_message}</p>}
    {candidate && <p className="review-notice">{candidate.uncertainty_reason}</p>}
    {media.inspector_note && <p className="review-notice"><strong>Field Note: </strong>{media.inspector_note}</p>}
    <div className="finding-fields"><label>Category<select aria-label="Category" required value={category} disabled={busy} onChange={(event) => setCategory(event.target.value)}><option value="">Select category</option>{categories.map((value) => <option key={value} value={value}>{value[0].toUpperCase() + value.slice(1)}</option>)}</select></label>
      <label>Room / Location<input required maxLength={200} value={location} disabled={busy} onChange={(event) => setLocation(event.target.value)} /></label></div>
    <label>Photo Caption<textarea aria-label="Photo Caption" required maxLength={500} rows={2} value={caption} disabled={busy} onChange={(event) => setCaption(event.target.value)} /></label>
    <label>Inspector Observation<textarea aria-label="Inspector Observation" required maxLength={1000} rows={5} value={observation} disabled={busy} onChange={(event) => setObservation(event.target.value)} /></label>
    <label>Review Decision<select aria-label="Review Decision" value={decision} disabled={busy} onChange={(event) => setDecision(event.target.value as ReviewInput['decision'])}><option value="needs_verification">Needs verification</option><option value="accepted">Accept reviewed finding</option><option value="rejected">Reject finding</option></select></label>
    <button className="primary-button" disabled={busy} type="submit">{busy ? <LoaderCircle className="spinning" size={16} /> : <Check size={16} />}Save review</button>
  </form>
}

export default function ReportWorkspace({ inspection, media, mediaHasMore }: { inspection: Inspection; media: Media[]; mediaHasMore: boolean }) {
  const [analyses, setAnalyses] = useState<Analysis[]>([])
  const [reviews, setReviews] = useState<Review[]>([])
  const [reports, setReports] = useState<Report[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [revision, setRevision] = useState(0)
  const [more, setMore] = useState({ analyses: false, reviews: false, reports: false })
  const [approved, setApproved] = useState(false)
  const approvalKey = useRef<{ signature: string; id: string } | null>(null)
  const analysisKey = useRef<string | null>(null)
  const selected = media.find((item) => item.id === selectedId) ?? media[0]
  const selectedAnalysis = analyses.filter((job) => job.media_asset_id === selected?.id).sort((left, right) => (right.created_at ?? '').localeCompare(left.created_at ?? ''))[0] ?? null
  const latest = new Map<string, Review>()
  for (const row of reviews) {
    const previous = latest.get(row.media_asset_id)
    if (!previous || row.reviewed_at > previous.reviewed_at || (row.reviewed_at === previous.reviewed_at && row.id > previous.id)) latest.set(row.media_asset_id, row)
  }
  const accepted = [...latest.values()].filter((row) => row.decision === 'accepted').sort((left, right) => left.id.localeCompare(right.id))
  const allPagesLoaded = !mediaHasMore && !more.analyses && !more.reviews && accepted.length <= 200

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([list<Analysis>(`/v1/inspections/${inspection.id}/analyses`, controller.signal, undefined, 100),
      list<Review>(`/v1/inspections/${inspection.id}/findings`, controller.signal, undefined, 100),
      list<Report>(`/v1/inspections/${inspection.id}/reports`, controller.signal, undefined, 20)])
      .then(([jobs, findings, snapshots]) => {
        if (controller.signal.aborted) return
        setAnalyses(jobs); setReviews(findings); setReports(snapshots)
        setMore({ analyses: jobs.length === 100, reviews: findings.length === 100, reports: snapshots.length === 20 }); setError(''); setLoaded(true)
      }).catch((failure) => { if (!controller.signal.aborted) { setError(failureText(failure)); setLoaded(false) } })
    return () => controller.abort()
  }, [inspection.id, revision])

  async function loadPages() {
    setBusy(true); setError('')
    try {
      if (more.analyses) { const page = await list<Analysis>(`/v1/inspections/${inspection.id}/analyses`, undefined, analyses.at(-1)?.id, 100); setAnalyses((current) => [...current, ...page]); setMore((current) => ({ ...current, analyses: page.length === 100 })) }
      if (more.reviews) { const page = await list<Review>(`/v1/inspections/${inspection.id}/findings`, undefined, reviews.at(-1)?.id, 100); setReviews((current) => [...current, ...page]); setMore((current) => ({ ...current, reviews: page.length === 100 })) }
      if (more.reports) { const page = await list<Report>(`/v1/inspections/${inspection.id}/reports`, undefined, reports.at(-1)?.id, 20); setReports((current) => [...current, ...page]); setMore((current) => ({ ...current, reports: page.length === 20 })) }
    } catch (failure) { setError(failureText(failure)) }
    finally { setBusy(false) }
  }
  async function analyze() {
    if (!selected) return
    setBusy(true); setError(''); setNotice('')
    analysisKey.current ??= crypto.randomUUID()
    try {
      const job = await create<Analysis>(`/v1/media/${selected.id}/analyses`, { requested_category: selected.requested_category }, analysisKey.current)
      setAnalyses((current) => [...current.filter((row) => row.id !== job.id), job]); analysisKey.current = null
      setNotice('Analysis queued. Refresh results to view its status.')
    } catch (failure) { setError(failureText(failure)) }
    finally { setBusy(false) }
  }
  async function save(payload: ReviewInput, key: string) {
    setBusy(true); setError(''); setNotice('')
    try {
      const result = await create<Review>(`/v1/inspections/${inspection.id}/findings`, payload, key)
      setReviews((current) => [...current.filter((row) => row.id !== result.id), result]); setApproved(false); setNotice('Inspector review saved.')
    } catch (failure) { setError(failureText(failure)) }
    finally { setBusy(false) }
  }
  async function download(report: Report) {
    setBusy(true); setError('')
    try {
      const response = await requestResponse(`/v1/reports/${report.id}/pdf`, {}, 120_000)
      if (!response.headers.get('content-type')?.startsWith('application/pdf')) throw new Error('The API did not return a PDF.')
      const url = URL.createObjectURL(await response.blob())
      const link = document.createElement('a'); link.href = url; link.download = `inspection-${report.id}.pdf`
      document.body.appendChild(link); link.click(); link.remove()
      setTimeout(() => URL.revokeObjectURL(url), 30_000)
    } catch (failure) { setError(failureText(failure)) }
    finally { setBusy(false) }
  }
  async function approve() {
    if (!approved || !accepted.length || !allPagesLoaded) return
    setBusy(true); setError(''); setNotice('')
    const payload = { finding_ids: accepted.map((row) => row.id), inspector_approved: true }
    const signature = JSON.stringify(payload)
    if (approvalKey.current?.signature !== signature) approvalKey.current = { signature, id: crypto.randomUUID() }
    try {
      const report = await create<Report>(`/v1/inspections/${inspection.id}/reports`, payload, approvalKey.current.id)
      setReports((current) => [...current.filter((row) => row.id !== report.id), report]); setApproved(false)
      setNotice('Approved report saved. Download its PDF below.')
    } catch (failure) { setError(failureText(failure)) }
    finally { setBusy(false) }
  }

  return <section className="review-workspace" aria-label="Inspector report review">
    <header className="review-heading"><div><h2>Finding Review & Report</h2><p>{inspection.property_address}</p></div><button className="secondary-button" disabled={busy} onClick={() => { setApproved(false); setRevision((value) => value + 1) }}><RefreshCw size={16} />Refresh results</button></header>
    {error && <div className="error-banner" role="alert">{error}</div>}{notice && <p className="review-notice" role="status">{notice}</p>}
    {!loaded ? <p className="review-notice">{error ? 'Review results are unavailable.' : 'Loading review results'}</p> : !media.length ? <p className="review-notice">No photo evidence attached.</p> : <div className="review-layout">
      <div className="review-evidence"><div className="photo-selector" aria-label="Select photograph">{media.map((item, index) => <button key={item.id} className={selected?.id === item.id ? 'selected' : ''} disabled={busy} onClick={() => { setSelectedId(item.id); analysisKey.current = null; setNotice('') }}><span>{String(index + 1).padStart(2, '0')}</span><span>{item.file_name}</span><small>{latest.get(item.id)?.decision.replaceAll('_', ' ') ?? 'Not reviewed'}</small></button>)}</div>
        {selected && <><EvidencePhoto key={selected.id} media={selected} className="review-original" /><div className="review-photo-actions"><strong>{selected.file_name}</strong><button className="secondary-button" disabled={busy || selectedAnalysis?.status === 'queued' || selectedAnalysis?.status === 'running'} onClick={() => void analyze()}><ScanSearch size={16} />Analyze photo</button></div></>}
      </div>
      {selected && <ReviewEditor key={`${selected.id}:${selectedAnalysis?.id ?? 'manual'}:${selectedAnalysis?.status}:${latest.get(selected.id)?.id ?? ''}`} media={selected} analysis={selectedAnalysis} previous={latest.get(selected.id)} busy={busy} save={save} />}
    </div>}
    {(more.analyses || more.reviews || more.reports) && <button className="text-button" disabled={busy} onClick={() => void loadPages()}><ArrowDown size={15} />Load more review records</button>}
    <div className="report-approval"><label><input type="checkbox" checked={approved} disabled={busy || !loaded || !accepted.length || !allPagesLoaded} onChange={(event) => setApproved(event.target.checked)} /><span>I approve the {accepted.length} accepted findings for this report.</span></label><button className="primary-button" disabled={busy || !approved || !accepted.length || !allPagesLoaded} onClick={() => void approve()}><Check size={16} />Approve report</button></div>
    {reports.length > 0 && <div className="approved-report-list"><h3>Approved Reports</h3>{[...reports].sort((left, right) => right.approved_at.localeCompare(left.approved_at)).map((report) => <div className="approved-report-row" key={report.id}><span><strong>{new Date(report.approved_at).toLocaleString()}</strong><small>{report.findings.length} findings / #{report.id.slice(0, 8)}</small></span><button className="secondary-button" disabled={busy} onClick={() => void download(report)}><Download size={16} />Download PDF</button></div>)}</div>}
  </section>
}