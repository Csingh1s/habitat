import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ArrowDown, Building2, LoaderCircle, Plus, Users, X } from 'lucide-react'
import { address, create } from './api'
import type { Client, Inspection, InspectionInput, Property, PropertyInput } from './api'
import type { View } from './App'

interface Props {
  mode: View
  clients: Client[]
  properties: Property[]
  onClose: () => void
  onSaved: (row: Client | Property | Inspection) => void
  onMoreClients: () => Promise<boolean>
  onMoreProperties: () => Promise<boolean>
}

export default function RecordDialog({ mode, clients, properties, onClose, onSaved, onMoreClients, onMoreProperties }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)
  const keys = useRef(new Map<string, { signature: string; key: string }>())
  const [newClient, setNewClient] = useState(mode === 'clients' || !clients.length)
  const [newProperty, setNewProperty] = useState(mode === 'properties' || !properties.length)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [moreClients, setMoreClients] = useState(clients.length > 0 && clients.length % 100 === 0)
  const [moreProperties, setMoreProperties] = useState(properties.length > 0 && properties.length % 100 === 0)
  const [loadingOptions, setLoadingOptions] = useState(false)
  const title = mode === 'inspections' ? 'New inspection' : mode === 'clients' ? 'New client' : 'New property'

  useEffect(() => { dialog.current?.showModal() }, [])
  function keyFor(path: string, payload: unknown) {
    const signature = JSON.stringify(payload)
    const existing = keys.current.get(path)
    if (existing?.signature === signature) return existing.key
    const key = crypto.randomUUID()
    keys.current.set(path, { signature, key })
    return key
  }
  async function more(type: 'clients' | 'properties') {
    setLoadingOptions(true); setError('')
    try { if (type === 'clients') setMoreClients(await onMoreClients()); else setMoreProperties(await onMoreProperties()) }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Could not load additional records.') }
    finally { setLoadingOptions(false) }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    const form = new FormData(event.currentTarget)
    const value = (name: string) => String(form.get(name) ?? '').trim()
    setBusy(true); setError('')
    try {
      let customer: Client | null = null
      let property: Property | null = null
      if (mode !== 'properties' && newClient) {
        const payload = { full_name: value('full_name'), email: value('email') || null }
        customer = await create<Client>('/v1/clients', payload, keyFor('client', payload))
      }
      if (mode === 'clients') { onSaved(customer!); return }
      if (newProperty) {
        const payload: PropertyInput = { address_line1: value('address_line1'), address_line2: value('address_line2'), city: value('city'), region: value('region'), postal_code: value('postal_code'), country: value('country') as 'CA' | 'US' }
        property = await create<Property>('/v1/properties', payload, keyFor('property', payload))
      }
      if (mode === 'properties') { onSaved(property!); return }
      const payload: InspectionInput = { client_id: customer?.id ?? value('client_id'), property_id: property?.id ?? value('property_id'), scheduled_for: value('scheduled_for') ? new Date(value('scheduled_for')).toISOString() : null }
      const inspection = await create<Inspection>('/v1/inspections', payload, keyFor('inspection', payload))
      onSaved(inspection)
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'The record could not be saved.') }
    finally { setBusy(false) }
  }

  return <dialog ref={dialog} className="record-dialog" aria-labelledby="dialog-title" onCancel={(event) => { event.preventDefault(); if (!busy) onClose() }}>
    <form onSubmit={(event) => void submit(event)}>
      <header className="dialog-heading"><div><span className="eyebrow">WORKSPACE RECORD</span><h2 id="dialog-title">{title}</h2></div><button type="button" className="icon-button" aria-label="Close dialog" title="Close dialog" disabled={busy} onClick={onClose}><X size={20} /></button></header>
      <div className="dialog-body"><fieldset disabled={busy} className="form-fields">
        {mode !== 'properties' && <section className="form-section"><div className="form-section-heading"><h3><Users size={17} />Client</h3>{mode === 'inspections' && <label className="checkbox-label"><input type="checkbox" checked={newClient} onChange={(event) => setNewClient(event.target.checked)} />Create new client</label>}</div>
          {newClient ? <div className="form-grid"><label>Full name<input name="full_name" required maxLength={200} autoComplete="name" placeholder="Client's full name" /></label><label>Email <span className="muted">(optional)</span><input name="email" type="email" maxLength={320} autoComplete="email" placeholder="name@example.com" /></label></div> : <><label>Existing client<select name="client_id" required defaultValue=""><option value="" disabled>Select a client</option>{clients.map((customer) => <option value={customer.id} key={customer.id}>{customer.full_name}{customer.email ? ` / ${customer.email}` : ''}</option>)}</select></label>{moreClients && <button type="button" className="text-button" disabled={loadingOptions} onClick={() => void more('clients')}><ArrowDown size={14} />Load more clients</button>}</>}
        </section>}
        {mode !== 'clients' && <section className="form-section"><div className="form-section-heading"><h3><Building2 size={17} />Property</h3>{mode === 'inspections' && <label className="checkbox-label"><input type="checkbox" checked={newProperty} onChange={(event) => setNewProperty(event.target.checked)} />Create new property</label>}</div>
          {newProperty ? <div className="form-grid"><label className="full-width">Street address<input name="address_line1" required maxLength={200} autoComplete="address-line1" placeholder="Street number and name" /></label><label className="full-width">Unit / suite <span className="muted">(optional)</span><input name="address_line2" maxLength={200} autoComplete="address-line2" /></label><label>City<input name="city" required maxLength={100} autoComplete="address-level2" /></label><label>Province / state<input name="region" required maxLength={100} autoComplete="address-level1" /></label><label>Postal / ZIP code<input name="postal_code" required maxLength={20} autoComplete="postal-code" /></label><label>Country<select name="country" defaultValue="CA" autoComplete="country"><option value="CA">Canada</option><option value="US">United States</option></select></label></div> : <><label>Existing property<select name="property_id" required defaultValue=""><option value="" disabled>Select a property</option>{properties.map((property) => <option value={property.id} key={property.id}>{address(property)}</option>)}</select></label>{moreProperties && <button type="button" className="text-button" disabled={loadingOptions} onClick={() => void more('properties')}><ArrowDown size={14} />Load more properties</button>}</>}
        </section>}
        {mode === 'inspections' && <section className="form-section schedule-section"><label>Scheduled date and time <span className="muted">(optional, local time)</span><input name="scheduled_for" type="datetime-local" /></label></section>}
      </fieldset>{error && <div className="error-banner" role="alert">{error}</div>}</div>
      <footer className="dialog-footer"><button type="button" className="secondary-button" disabled={busy} onClick={onClose}>Cancel</button><button type="submit" className="primary-button" disabled={busy || loadingOptions}>{busy ? <LoaderCircle size={17} className="spinning" /> : <Plus size={17} />}{busy ? 'Saving' : mode === 'inspections' ? 'Create inspection' : mode === 'clients' ? 'Create client' : 'Create property'}</button></footer>
    </form>
  </dialog>
}