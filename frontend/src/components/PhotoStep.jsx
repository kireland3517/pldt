import React, { useState, useRef, useCallback, useEffect } from 'react'
import { tagPhoto, getSession, updateInputs } from '../api'

const ROOM_ZONES = [
  { value: 'exterior_front',   label: 'Exterior — Front',
    priority: ['SID-01','WIN-01','XDR-01','LAND-01','PWASH-01','GAR-01','ROOF-01','DRV-01','ACCT-01','BELL-01','MBOX-01','XLT-01'] },
  { value: 'exterior_back',    label: 'Exterior — Back/Side',
    priority: ['SID-01','WIN-01','GUT-01','OUT-01','XLT-01'] },
  { value: 'deck_porch',       label: 'Deck / Porch / Patio',
    priority: ['DECK-01','PRCH-01','OUT-01','XLT-01','GUT-01'] },
  { value: 'roof',             label: 'Roof',
    priority: ['ROOF-01','GUT-01','ATTIC-01'] },
  { value: 'yard_lot',         label: 'Yard / Lot / Driveway',
    priority: ['LAND-01','DRV-01','GUT-01','MBOX-01','BELL-01'] },
  { value: 'kitchen',          label: 'Kitchen',
    priority: ['KIT-01','FLR-01','PNT-01','ILT-01','PLMB-01','IHW-01'] },
  { value: 'primary_bath',     label: 'Primary Bathroom',
    priority: ['BTHP-01','VAN-01','PLMB-01','VENT-01','FLR-01','PNT-01'] },
  { value: 'secondary_bath',   label: 'Secondary Bathroom',
    priority: ['BTHS-01','VAN-01','PLMB-01','VENT-01','FLR-01','PNT-01'] },
  { value: 'living_room',      label: 'Living Room',
    priority: ['FLR-01','PNT-01','ILT-01','WIN-01','IHW-01','IDR-01'] },
  { value: 'dining_room',      label: 'Dining Room',
    priority: ['FLR-01','PNT-01','ILT-01','WIN-01','IHW-01'] },
  { value: 'primary_bedroom',  label: 'Primary Bedroom',
    priority: ['FLR-01','PNT-01','ILT-01','WIN-01','IDR-01','IHW-01'] },
  { value: 'bedroom',          label: 'Bedroom (other)',
    priority: ['FLR-01','PNT-01','ILT-01','WIN-01'] },
  { value: 'mechanical',       label: 'Mechanical / Utility',
    priority: ['HVAC-01','WH-HTR-01','ELEC-01','PLMB-01','DUCT-01','WSHR-01','DET-01'] },
  { value: 'crawlspace',       label: 'Crawlspace / Foundation', priority: ['FND-01'] },
  { value: 'garage',           label: 'Garage',
    priority: ['GAR-01','ELEC-01','OUT-01','DET-01'] },
  { value: 'attic',            label: 'Attic',
    priority: ['ATTIC-01','ELEC-01','ROOF-01','DET-01'] },
  { value: 'other',            label: 'Other / General', priority: [] },
]

const CONDITIONS = ['good', 'fair', 'poor', 'failed', 'unknown']
const SEVERITIES  = ['none', 'low', 'medium', 'high']

const ALWAYS_COMMON = new Set([
  'ROOF-01','FND-01','WIN-01','XDR-01','LAND-01','HVAC-01','WH-HTR-01',
  'ELEC-01','PLMB-01','DET-01','FLR-01','PNT-01','KIT-01','BTHP-01',
  'DECK-01','PRCH-01','GAR-01','GUT-01','VENT-01',
])

// Safety- and lender-eligible components that require EXPLICIT seller confirmation
// before a vision-detected defect can enter the mandatory Floor.
// Default: OUT. Seller "yes" moves it IN. "no" or no answer = staged out.
const FLOOR_ELIGIBLE = {
  'ROOF-01':   { why: 'Lenders may require repairs or replacement before approving a buyer's loan.' },
  'FND-01':    { why: 'Active water or structural movement is a safety concern and can block loan approval.' },
  'GUT-01':    { why: 'Gutters causing water intrusion into the home are typically flagged by lenders.' },
  'DECK-01':   { why: 'Open risers, a loose railing, or rot are safety hazards lenders may require fixed.' },
  'PRCH-01':   { why: 'A missing or loose handrail and open risers are safety hazards.' },
  'OUT-01':    { why: 'Missing outlet covers or a shock hazard are safety issues.' },
  'GAR-01':    { why: 'A non-functional garage door is typically required by lenders to be working.' },
  'HVAC-01':   { why: 'Lenders usually require a functioning HVAC system.' },
  'WH-HTR-01': { why: 'Lenders typically require a functional, non-leaking water heater.' },
  'ELEC-01':   { why: 'Exposed wiring, open junction boxes, or an unsafe panel are safety issues lenders will flag.' },
  'PLMB-01':   { why: 'An active leak or non-functional water supply can block loan approval.' },
  'DET-01':    { why: 'Smoke and CO detectors are required by most states and lenders.' },
}

// Human-readable names for the absence panel (components not detected by vision)
const COMPONENT_NAMES = {
  'ROOF-01': 'Roof (asphalt shingle)',
  'FND-01': 'Foundation / crawlspace / basement',
  'SID-01': 'Siding (vinyl)',
  'GUT-01': 'Gutters / downspouts / drainage',
  'WIN-01': 'Windows (general)',
  'SCR-01': 'Window screens',
  'DECK-01': 'Deck',
  'PRCH-01': 'Front porch / steps / railings',
  'DRV-01': 'Driveway',
  'XDR-01': 'Exterior doors / entry',
  'XLT-01': 'Exterior lighting',
  'LAND-01': 'Landscaping / yard',
  'PWASH-01': 'Pressure wash (service)',
  'ACCT-01': 'Decorative accents / shutters',
  'MBOX-01': 'Mailbox',
  'BELL-01': 'Doorbell',
  'OUT-01': 'Exterior outlets / GFCI',
  'GAR-01': 'Garage door / opener',
  'HVAC-01': 'HVAC system (furnace + AC)',
  'WH-HTR-01': 'Water heater',
  'ELEC-01': 'Electrical panel / wiring',
  'PLMB-01': 'Plumbing supply / drain',
  'DET-01': 'Smoke / CO detectors',
  'DUCT-01': 'Duct system (clean / inspect)',
  'REM-01': 'Smoke / odor remediation',
  'VENT-01': 'Bathroom / exhaust fans',
  'IHW-01': 'Interior hardware (handles / knobs)',
  'FLR-01': 'Flooring (carpet / LVP / hardwood)',
  'IDR-01': 'Interior doors',
  'ILT-01': 'Interior lighting / fixtures',
  'PNT-01': 'Interior paint',
  'KIT-01': 'Kitchen (cabinets / counters)',
  'VAN-01': 'Vanity / bathroom fixtures',
  'BTHP-01': 'Primary bathroom',
  'BTHS-01': 'Secondary bathroom(s)',
  'WSHR-01': 'Washer / dryer hookups',
  'ATTIC-01': 'Attic access / insulation',
}

// ── merge helpers ────────────────────────────────────────────────────────────

// Merge one tag into the running component map.
// Higher-confidence reading wins for condition/severity/evidence.
// Seller edits (seller_note) are preserved across merges.
function mergeSingleTag(map, tag) {
  const cid = tag.component_id
  const ex  = map[cid]
  const src = tag.source_photo
  const sources = ex
    ? [...new Set([...(ex.sources || []), src].filter(Boolean))]
    : [src].filter(Boolean)

  if (!ex) {
    // First detection of this component
    return {
      ...map,
      [cid]: {
        component_id:   cid,
        display_name:   tag.display_name || cid,
        present:        tag.present,
        condition:      tag.condition,
        severity:       tag.severity,
        confidence:     tag.confidence,
        evidence:       tag.evidence,
        sources,
        seller_note:    '',
        orig_present:   tag.present,
        orig_condition: tag.condition,
        orig_severity:  tag.severity,
      },
    }
  }

  if (tag.confidence > ex.confidence) {
    // Better reading — update vision fields, keep seller edits
    return {
      ...map,
      [cid]: {
        ...ex,
        present:        tag.present,
        condition:      tag.condition,
        severity:       tag.severity,
        confidence:     tag.confidence,
        evidence:       tag.evidence,
        sources,
        orig_present:   tag.present,
        orig_condition: tag.condition,
        orig_severity:  tag.severity,
      },
    }
  }

  // Lower confidence — just add source, keep everything else
  return { ...map, [cid]: { ...ex, sources } }
}

function mergeAllTags(tags) {
  return tags.reduce((map, tag) => mergeSingleTag(map, tag), {})
}

// ── image helpers ────────────────────────────────────────────────────────────

async function downscale(file, maxPx = 1600) {
  return new Promise((resolve) => {
    const img    = new Image()
    const blobUrl = URL.createObjectURL(file)
    img.onload = () => {
      URL.revokeObjectURL(blobUrl)
      const { naturalWidth: w, naturalHeight: h } = img
      if (w <= maxPx && h <= maxPx) { resolve(file); return }
      const scale   = maxPx / Math.max(w, h)
      const canvas  = document.createElement('canvas')
      canvas.width  = Math.round(w * scale)
      canvas.height = Math.round(h * scale)
      canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height)
      canvas.toBlob(
        blob => resolve(new File([blob], file.name, { type: 'image/jpeg' })),
        'image/jpeg', 0.85
      )
    }
    img.onerror = () => { URL.revokeObjectURL(blobUrl); resolve(file) }
    img.src = blobUrl
  })
}

async function withRetry(fn, maxAttempts = 3) {
  let lastErr
  for (let i = 0; i < maxAttempts; i++) {
    try { return await fn() }
    catch (err) {
      lastErr = err
      if (i < maxAttempts - 1) await new Promise(r => setTimeout(r, 1000 * Math.pow(2, i)))
    }
  }
  throw lastErr
}

// ── component ────────────────────────────────────────────────────────────────

export default function PhotoStep({ sessionId, onDone }) {
  const [photos, setPhotos]             = useState([])
  const [componentMap, setComponentMap] = useState({})
  const [resumedFromSession, setResumedFromSession] = useState(false)
  const [loadingResume, setLoadingResume]           = useState(true)
  const [unconfirmedAnswers, setUnconfirmedAnswers] = useState({})
  const [floorConfirm, setFloorConfirm] = useState({}) // cid -> 'yes' | 'no'
  const inputRef   = useRef()
  const queueRef   = useRef([])
  const runningRef = useRef(false)

  // ── load existing tags from Supabase on mount ──────────────────────────────
  useEffect(() => {
    async function loadExisting() {
      try {
        const session = await getSession(sessionId)
        const tags    = session.photo_tags || []
        if (tags.length > 0) {
          setComponentMap(mergeAllTags(tags))
          setResumedFromSession(true)
        }
      } catch (_) {
        // silent — fall through to fresh upload
      } finally {
        setLoadingResume(false)
      }
    }
    loadExisting()
  }, [sessionId])

  // ── sequential queue ──────────────────────────────────────────────────────
  const drainQueue = useCallback(async () => {
    if (runningRef.current) return
    const item = queueRef.current.shift()
    if (!item) return
    runningRef.current = true

    const { idx, file, room_zone } = item
    setPhotos(prev => prev.map((p, i) => i === idx ? { ...p, status: 'tagging', error: null } : p))

    try {
      const small  = await downscale(file)
      const result = await withRetry(() => tagPhoto(sessionId, small, room_zone), 3)
      setPhotos(prev => prev.map((p, i) =>
        i === idx ? { ...p, status: 'done', tagCount: result.tags.length, error: null } : p
      ))
      setComponentMap(prev => {
        const newMap = result.tags.reduce((m, tag) => mergeSingleTag(m, tag), prev)
        // Fire-and-forget draft save so a reload can recover without re-tagging
        const draft = Object.values(newMap).map(c => ({
          component_id: c.component_id,
          display_name: c.display_name || c.component_id,
          present:      c.present,
          condition:    c.condition,
          severity:     c.severity,
          confidence:   c.confidence,
          evidence:     c.evidence,
          source_photo: (c.sources || [])[0] || 'merged',
        }))
        updateInputs(sessionId, { seller_inputs: { _photo_tags_draft: draft } }).catch(() => {})
        return newMap
      })
    } catch (err) {
      setPhotos(prev => prev.map((p, i) =>
        i === idx ? { ...p, status: 'error', error: err.message } : p
      ))
    }

    runningRef.current = false
    if (queueRef.current.length > 0) drainQueue()
  }, [sessionId])

  // ── file input ────────────────────────────────────────────────────────────
  function handleFiles(e) {
    const files = Array.from(e.target.files)
    if (!files.length) return
    const entries = files.map(f => ({
      file: f, url: URL.createObjectURL(f), room_zone: '',
      status: 'needs_room', tagCount: 0, error: null,
    }))
    setPhotos(prev => [...prev, ...entries])
    e.target.value = ''
  }

  function setRoom(idx, room_zone) {
    setPhotos(prev => {
      const updated = prev.map((p, i) => i === idx ? { ...p, room_zone } : p)
      if (room_zone) {
        queueRef.current.push({ idx, file: updated[idx].file, room_zone })
        drainQueue()
      }
      return updated
    })
  }

  function retag(idx) {
    setPhotos(prev => {
      const p = prev[idx]
      if (!p.room_zone) return prev
      queueRef.current.push({ idx, file: p.file, room_zone: p.room_zone })
      drainQueue()
      return prev
    })
  }

  function removePhoto(idx) {
    setPhotos(prev => {
      URL.revokeObjectURL(prev[idx].url)
      queueRef.current = queueRef.current
        .filter(item => item.idx !== idx)
        .map(item => ({ ...item, idx: item.idx > idx ? item.idx - 1 : item.idx }))
      return prev.filter((_, i) => i !== idx)
    })
  }

  // ── component map edits ───────────────────────────────────────────────────
  function editComponent(cid, field, value) {
    setComponentMap(prev => ({ ...prev, [cid]: { ...prev[cid], [field]: value } }))
  }

  // ── derived state ─────────────────────────────────────────────────────────
  const taggingCount = photos.filter(p => p.status === 'tagging').length
  const queueDepth   = queueRef.current.length
  const allPhotoDone = photos.length === 0 ||
    photos.every(p => ['done','error','needs_room'].includes(p.status))

  const components = Object.values(componentMap).sort((a, b) => b.confidence - a.confidence)
  const showReview = !loadingResume && components.length > 0

  const lowConfAbsent  = components.filter(c => !c.present && c.confidence < 0.75).map(c => c.component_id)
  const untaggedAlways = [...ALWAYS_COMMON].filter(cid => !(cid in componentMap))
  const unconfirmedCids = [...new Set([...lowConfAbsent, ...untaggedAlways])]

  // Floor gate: vision-detected safety/lender defects that need explicit confirmation.
  // Threshold: present + (poor|failed) + (medium|high severity) + in eligible set.
  // Default is OUT — these are staged, not written, until seller says yes.
  const floorCandidates = components.filter(c =>
    c.present &&
    FLOOR_ELIGIBLE[c.component_id] &&
    (c.condition === 'poor' || c.condition === 'failed') &&
    (c.severity === 'medium' || c.severity === 'high') &&
    c.confidence >= 0.5
  )
  const allGateAnswered = floorCandidates.every(c => floorConfirm[c.component_id] != null)

  // ── continue ──────────────────────────────────────────────────────────────
  function handleContinue() {
    const photoTagsForCapture = components.map(c => ({
      component_id: c.component_id,
      tag: c.condition !== 'unknown' ? c.condition : (c.present ? 'present' : 'not_present'),
      confidence:   c.confidence,
      source_photo: (c.sources || [])[0] || 'merged',
    }))

    // Collect review-table edits keyed by component_id
    const confirmedMap = {}
    for (const c of components) {
      const hasEdit = (
        c.present   !== c.orig_present   ||
        c.condition !== c.orig_condition ||
        c.severity  !== c.orig_severity  ||
        c.seller_note.trim() !== ''
      )
      if (hasEdit) {
        const entry = { component_id: c.component_id }
        if (c.present   !== c.orig_present)   entry.present    = c.present
        if (c.condition !== c.orig_condition) entry.condition  = c.condition
        if (c.severity  !== c.orig_severity)  entry.severity   = c.severity
        if (c.seller_note.trim())             entry.seller_note = c.seller_note.trim()
        confirmedMap[c.component_id] = entry
      }
    }

    // Floor gate answers override the review table for safety/lender components.
    // 'yes' → keep vision's defect reading, mark as seller-confirmed (enters Floor).
    // 'no'  → clear condition to 'good' so it cannot trigger floor membership.
    // Unconfirmed (shouldn't reach here if gate is blocking, but guard it) → also cleared.
    for (const c of floorCandidates) {
      const answer = floorConfirm[c.component_id]
      if (answer === 'yes') {
        confirmedMap[c.component_id] = {
          ...(confirmedMap[c.component_id] || {}),
          component_id: c.component_id,
          present:   true,
          condition: c.condition,
          severity:  c.severity,
        }
      } else {
        // 'no' or unconfirmed: stage out — component is present but defect is not confirmed
        confirmedMap[c.component_id] = {
          component_id: c.component_id,
          present:   true,
          condition: 'good',
          severity:  'none',
        }
      }
    }

    const sellerConfirmedTags      = Object.values(confirmedMap)
    const absencePresenceAnswers   = Object.entries(unconfirmedAnswers).map(([cid, val]) => ({
      question_id: `P-UNCONFIRMED-${cid}`, component_id: cid, answer: val,
    }))

    onDone({ photoTagsForCapture, sellerConfirmedTags, absencePresenceAnswers })
  }

  // ── render ────────────────────────────────────────────────────────────────
  if (loadingResume) {
    return <p style={{ fontSize: 13, color: '#888' }}>Loading…</p>
  }

  return (
    <div>
      <h2 style={{ fontSize: 16, marginBottom: 8 }}>Photos</h2>

      {resumedFromSession && photos.length === 0 && (
        <div style={resumeBanner}>
          <strong>Loaded {components.length} components</strong> from your previous photo analysis.
          Review and correct below, or add more photos.
        </div>
      )}

      {/* ── upload section ── */}
      <div style={{ marginBottom: 16 }}>
        <input ref={inputRef} type="file" accept="image/*" multiple
          style={{ display: 'none' }} onChange={handleFiles} />
        <button style={btnStyle} onClick={() => inputRef.current.click()}>
          {resumedFromSession ? 'Add more photos' : 'Add photos'}
        </button>
        {(taggingCount > 0 || queueDepth > 0) && (
          <span style={{ fontSize: 12, color: '#555', marginLeft: 12 }}>
            Tagging one at a time…{queueDepth > 0 && ` ${queueDepth} waiting`}
          </span>
        )}
      </div>

      {/* ── per-photo status cards ── */}
      {photos.map((p, pi) => (
        <div key={pi} style={cardStyle}>
          <img src={p.url} alt={p.file.name} style={thumbStyle} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
              <span style={{ fontSize: 13, fontWeight: 500, wordBreak: 'break-all', flex: 1 }}>
                {p.file.name}
              </span>
              <button onClick={() => removePhoto(pi)} disabled={p.status === 'tagging'}
                title="Remove photo"
                style={{ marginLeft: 8, fontSize: 11, color: '#c00', background: 'none', border: 'none', cursor: p.status === 'tagging' ? 'not-allowed' : 'pointer', flexShrink: 0 }}>
                ✕ Remove
              </button>
            </div>

            <label style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
              Room:{' '}
              <select value={p.room_zone} onChange={e => setRoom(pi, e.target.value)}
                style={{ fontSize: 12 }} disabled={p.status === 'tagging'}>
                <option value="">— pick room —</option>
                {ROOM_ZONES.map(z => <option key={z.value} value={z.value}>{z.label}</option>)}
              </select>
            </label>

            {p.status === 'needs_room' && <span style={badge('gray')}>Pick a room to start tagging</span>}
            {p.status === 'tagging'    && <span style={badge('blue')}>Tagging…</span>}
            {p.status === 'done'       && (
              <span style={badge('green')}>
                {p.tagCount} component{p.tagCount !== 1 ? 's' : ''} detected
                {' · '}
                <button style={{ fontSize: 11, background: 'none', border: 'none', cursor: 'pointer', color: '#155724', padding: 0 }}
                  onClick={() => retag(pi)}>re-tag</button>
              </span>
            )}
            {p.status === 'error' && (
              <span style={{ fontSize: 12, color: '#c00' }}>
                Failed after 3 attempts: {p.error}{' '}
                <button style={{ fontSize: 11, cursor: 'pointer' }} onClick={() => retag(pi)}>Retry</button>
              </span>
            )}
          </div>
        </div>
      ))}

      {photos.length > 0 && !allPhotoDone && (
        <p style={{ fontSize: 13, color: '#888', margin: '12px 0' }}>
          Waiting for all photos to finish tagging…
        </p>
      )}

      {/* ── component review table (deduplicated) ── */}
      {showReview && (
        <div style={{ marginTop: 24 }}>
          <h3 style={{ fontSize: 14, marginBottom: 4 }}>
            Component review — {components.length} detected
          </h3>
          <p style={{ fontSize: 12, color: '#666', marginBottom: 10 }}>
            Vision's assessment is a draft. Correct any field — your edits override vision.
            "Present" means this component exists in the home.
          </p>

          <div style={{ overflowX: 'auto' }}>
            <table style={tableStyle}>
              <thead>
                <tr>
                  <th style={th}>Component</th>
                  <th style={th}>Present</th>
                  <th style={th}>Condition <em style={{ fontWeight: 400 }}>(vision draft)</em></th>
                  <th style={th}>Severity</th>
                  <th style={th}>Conf</th>
                  <th style={th}>Evidence</th>
                  <th style={th}>Photos</th>
                  <th style={th}>Your note</th>
                </tr>
              </thead>
              <tbody>
                {components.map(c => {
                  const edited = (
                    c.present   !== c.orig_present   ||
                    c.condition !== c.orig_condition ||
                    c.severity  !== c.orig_severity  ||
                    c.seller_note.trim() !== ''
                  )
                  return (
                    <tr key={c.component_id} style={{ background: edited ? '#fffbe6' : 'transparent' }}>
                      <td style={td} title={c.component_id}>{c.display_name}</td>
                      <td style={td}>
                        <select style={cellSelect}
                          value={c.present ? 'yes' : 'no'}
                          onChange={e => editComponent(c.component_id, 'present', e.target.value === 'yes')}>
                          <option value="yes">yes</option>
                          <option value="no">no</option>
                        </select>
                      </td>
                      <td style={td}>
                        <select style={cellSelect} value={c.condition}
                          onChange={e => editComponent(c.component_id, 'condition', e.target.value)}>
                          {CONDITIONS.map(v => <option key={v} value={v}>{v}</option>)}
                        </select>
                      </td>
                      <td style={td}>
                        <select style={cellSelect} value={c.severity}
                          onChange={e => editComponent(c.component_id, 'severity', e.target.value)}>
                          {SEVERITIES.map(v => <option key={v} value={v}>{v}</option>)}
                        </select>
                      </td>
                      <td style={{ ...td, fontSize: 11, color: edited ? '#b45309' : '#555' }}>
                        {edited ? 'edited' : `${(c.confidence * 100).toFixed(0)}%`}
                      </td>
                      <td style={{ ...td, fontSize: 11, color: '#777', maxWidth: 200 }}>{c.evidence}</td>
                      <td style={{ ...td, fontSize: 11, color: '#888' }}>
                        {(c.sources || []).length > 0
                          ? `${c.sources.length} photo${c.sources.length !== 1 ? 's' : ''}`
                          : '—'}
                      </td>
                      <td style={td}>
                        <input type="text" style={{ fontSize: 11, width: 130 }}
                          placeholder="optional note"
                          value={c.seller_note}
                          onChange={e => editComponent(c.component_id, 'seller_note', e.target.value)} />
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* ── unconfirmed absence panel ── */}
          {unconfirmedCids.length > 0 && (
            <div style={{ border: '1px solid #ffc107', borderRadius: 4, padding: 14, marginTop: 16, background: '#fffbe6' }}>
              <strong style={{ fontSize: 13 }}>
                {unconfirmedCids.length} component{unconfirmedCids.length !== 1 ? 's' : ''} not detected — does this home have them?
              </strong>
              <p style={{ fontSize: 12, color: '#666', margin: '4px 0 10px' }}>
                Vision didn't see these clearly. Answer to include them in the analysis.
              </p>
              {unconfirmedCids.map(cid => (
                <div key={cid} style={{ marginBottom: 6, fontSize: 13 }}>
                  <span style={{ fontSize: 13 }}>{COMPONENT_NAMES[cid] || cid}</span>
                  {' — '}
                  {['yes','no','unsure'].map(val => (
                    <label key={val} style={{ marginRight: 12 }}>
                      <input type="radio" name={`unc_${cid}`} value={val}
                        checked={unconfirmedAnswers[cid] === val}
                        onChange={() => setUnconfirmedAnswers(p => ({ ...p, [cid]: val }))} />
                      {' '}{val}
                    </label>
                  ))}
                </div>
              ))}
            </div>
          )}

          {/* ── floor gate: safety/lender defects require explicit confirmation ── */}
          {floorCandidates.length > 0 && (
            <div style={floorGateStyle}>
              <strong style={{ fontSize: 13 }}>
                {floorCandidates.length === 1
                  ? 'Vision spotted 1 issue that may require mandatory repair'
                  : `Vision spotted ${floorCandidates.length} issues that may require mandatory repair`}
              </strong>
              <p style={{ fontSize: 12, color: '#555', margin: '6px 0 14px', lineHeight: 1.5 }}>
                These items are <em>staged</em> — they won't count as required work unless you confirm
                they're accurate. Look at the evidence below and answer honestly.
                A genuine false-positive is easy to reject.
              </p>
              {floorCandidates.map(c => {
                const meta   = FLOOR_ELIGIBLE[c.component_id] || {}
                const answer = floorConfirm[c.component_id]
                return (
                  <div key={c.component_id} style={{
                    marginBottom: 16, paddingBottom: 16,
                    borderBottom: '1px solid #e8c97a',
                  }}>
                    <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4 }}>
                      {c.display_name}
                    </div>
                    {c.evidence && (
                      <div style={{ fontSize: 12, color: '#555', marginBottom: 4 }}>
                        <em>What vision saw:</em> {c.evidence}
                      </div>
                    )}
                    <div style={{ fontSize: 12, color: '#7a5c00', marginBottom: 8 }}>
                      {meta.why}
                    </div>
                    <div style={{ fontSize: 13 }}>
                      <strong>Can you confirm that's accurate?</strong>
                    </div>
                    <div style={{ marginTop: 6 }}>
                      <label style={{ marginRight: 20, fontSize: 13, cursor: 'pointer' }}>
                        <input type="radio" name={`floor_${c.component_id}`} value="yes"
                          checked={answer === 'yes'}
                          onChange={() => setFloorConfirm(prev => ({ ...prev, [c.component_id]: 'yes' }))}
                          style={{ marginRight: 4 }} />
                        Yes, that's accurate
                      </label>
                      <label style={{ fontSize: 13, cursor: 'pointer' }}>
                        <input type="radio" name={`floor_${c.component_id}`} value="no"
                          checked={answer === 'no'}
                          onChange={() => setFloorConfirm(prev => ({ ...prev, [c.component_id]: 'no' }))}
                          style={{ marginRight: 4 }} />
                        No, that's not right
                      </label>
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          <div style={{ marginTop: 20 }}>
            {!allPhotoDone && (
              <p style={{ fontSize: 12, color: '#888', marginBottom: 8 }}>
                Photos still processing — you can review above and continue when ready.
              </p>
            )}
            {floorCandidates.length > 0 && !allGateAnswered && (
              <p style={{ fontSize: 12, color: '#b45309', marginBottom: 8 }}>
                Answer each question above before continuing.
              </p>
            )}
            <button style={btnStyle} onClick={handleContinue}
              disabled={floorCandidates.length > 0 && !allGateAnswered}>
              Continue to questionnaire
            </button>
          </div>
        </div>
      )}

      {/* fresh start, no photos yet */}
      {!resumedFromSession && photos.length === 0 && (
        <div style={{ marginTop: 12 }}>
          <button style={{ ...btnStyle, background: '#eee' }}
            onClick={() => onDone({ photoTagsForCapture: [], sellerConfirmedTags: [], absencePresenceAnswers: [] })}>
            Skip photos
          </button>
        </div>
      )}
    </div>
  )
}

const btnStyle   = { padding: '8px 20px', fontSize: 14, cursor: 'pointer' }
const cardStyle  = { display: 'flex', gap: 12, marginTop: 12, padding: 10, border: '1px solid #ddd', borderRadius: 4 }
const thumbStyle = { width: 64, height: 64, objectFit: 'cover', borderRadius: 2, flexShrink: 0 }
const tableStyle = { borderCollapse: 'collapse', width: '100%', fontSize: 12 }
const th         = { textAlign: 'left', padding: '4px 6px', borderBottom: '1px solid #ccc', fontWeight: 600, whiteSpace: 'nowrap', background: '#f9f9f9' }
const td         = { padding: '3px 6px', borderBottom: '1px solid #eee', verticalAlign: 'middle' }
const cellSelect = { fontSize: 11, padding: '1px 2px' }
const resumeBanner = {
  background: '#e8f4fd', border: '1px solid #bee3f8', borderRadius: 4,
  padding: '10px 14px', marginBottom: 16, fontSize: 13,
}
const floorGateStyle = {
  background: '#fffbe6', border: '2px solid #f0c040', borderRadius: 6,
  padding: '16px 18px', marginTop: 20,
}
const badge = (color) => ({
  display: 'inline-block', fontSize: 11, padding: '1px 7px', borderRadius: 10,
  background: color === 'green' ? '#d4edda' : color === 'blue' ? '#cce5ff' : '#eee',
  color:      color === 'green' ? '#155724' : color === 'blue' ? '#004085' : '#555',
})
