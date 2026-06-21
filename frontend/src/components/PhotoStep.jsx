import React, { useState, useRef, useCallback } from 'react'
import { tagPhoto } from '../api'

const ROOM_ZONES = [
  // ---- exterior living spaces ----
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
  // ---- interior rooms ----
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
    priority: ['FLR-01','PNT-01','ILT-01','WIN-01','IHW-01','IDR-01'] },
  { value: 'bedroom',          label: 'Bedroom (other)',
    priority: ['FLR-01','PNT-01','ILT-01','WIN-01'] },
  // ---- systems / structure ----
  { value: 'mechanical',       label: 'Mechanical / Utility',
    priority: ['HVAC-01','WH-HTR-01','ELEC-01','PLMB-01','DUCT-01','WSHR-01','DET-01'] },
  { value: 'crawlspace',       label: 'Crawlspace / Foundation',
    priority: ['FND-01'] },
  { value: 'garage',           label: 'Garage',
    priority: ['GAR-01','ELEC-01','OUT-01','DET-01'] },
  { value: 'attic',            label: 'Attic',
    priority: ['ATTIC-01','ELEC-01','ROOF-01','DET-01'] },
  { value: 'other',            label: 'Other / General', priority: [] },
]

const CONDITIONS = ['good', 'fair', 'poor', 'failed', 'unknown']
const SEVERITIES = ['none', 'low', 'medium', 'high']

const ALWAYS_COMMON = new Set([
  'ROOF-01','FND-01','WIN-01','XDR-01','LAND-01','HVAC-01','WH-HTR-01',
  'ELEC-01','PLMB-01','DET-01','FLR-01','PNT-01','KIT-01','BTHP-01',
  'DECK-01','PRCH-01','GAR-01','GUT-01','VENT-01',
])

// ---- helpers ----------------------------------------------------------------

function initEditedTag(raw) {
  return {
    ...raw,
    orig_present:   raw.present,
    orig_condition: raw.condition,
    orig_severity:  raw.severity,
    seller_note:    '',
    seller_confirmed: false,
  }
}

function fieldEdited(tag) {
  return (
    tag.present   !== tag.orig_present   ||
    tag.condition !== tag.orig_condition ||
    tag.severity  !== tag.orig_severity  ||
    tag.seller_note.trim() !== ''
  )
}

// Resize to max 1600px on longest side; returns a new File (JPEG 85%)
async function downscale(file, maxPx = 1600) {
  return new Promise((resolve) => {
    const img = new Image()
    const blobUrl = URL.createObjectURL(file)
    img.onload = () => {
      URL.revokeObjectURL(blobUrl)
      const { naturalWidth: w, naturalHeight: h } = img
      if (w <= maxPx && h <= maxPx) { resolve(file); return }
      const scale = maxPx / Math.max(w, h)
      const canvas = document.createElement('canvas')
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

// Retry fn up to maxAttempts times with exponential backoff (1s, 2s, 4s)
async function withRetry(fn, maxAttempts = 3) {
  let lastErr
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try { return await fn() }
    catch (err) {
      lastErr = err
      if (attempt < maxAttempts - 1) {
        await new Promise(r => setTimeout(r, 1000 * Math.pow(2, attempt)))
      }
    }
  }
  throw lastErr
}

// ---- component --------------------------------------------------------------

export default function PhotoStep({ sessionId, onDone }) {
  const [photos, setPhotos]               = useState([])
  const [unconfirmedAnswers, setUnconfirmedAnswers] = useState({})
  const inputRef = useRef()

  // Sequential queue: { idx, file, room_zone }[]
  const queueRef   = useRef([])
  const runningRef = useRef(false)

  // ---- queue drain ----------------------------------------------------------
  const drainQueue = useCallback(async () => {
    if (runningRef.current) return
    const item = queueRef.current.shift()
    if (!item) return
    runningRef.current = true

    const { idx, file, room_zone } = item

    // Mark tagging
    setPhotos(prev => prev.map((p, i) =>
      i === idx ? { ...p, status: 'tagging', error: null } : p
    ))

    try {
      const small  = await downscale(file)
      const result = await withRetry(() => tagPhoto(sessionId, small, room_zone), 3)
      const editedTags = result.tags.map(initEditedTag)
      setPhotos(prev => prev.map((p, i) =>
        i === idx ? { ...p, status: 'done', rawTags: result.tags, editedTags, error: null } : p
      ))
    } catch (err) {
      setPhotos(prev => prev.map((p, i) =>
        i === idx ? { ...p, status: 'error', error: err.message } : p
      ))
    }

    runningRef.current = false
    // Process next item in queue (if any)
    if (queueRef.current.length > 0) drainQueue()
  }, [sessionId])

  // ---- file selection -------------------------------------------------------
  function handleFiles(e) {
    const files = Array.from(e.target.files)
    if (!files.length) return
    const entries = files.map(f => ({
      file: f,
      url: URL.createObjectURL(f),
      room_zone: '',
      status: 'needs_room',
      rawTags: [],
      editedTags: [],
      error: null,
    }))
    setPhotos(prev => [...prev, ...entries])
    e.target.value = ''
  }

  // ---- room assignment → enqueue -------------------------------------------
  function setRoom(idx, room_zone) {
    setPhotos(prev => prev.map((p, i) => i === idx ? { ...p, room_zone } : p))
    if (room_zone) {
      // Get the file from current state
      setPhotos(prev => {
        const file = prev[idx].file
        queueRef.current.push({ idx, file, room_zone })
        drainQueue()
        return prev
      })
    }
  }

  // ---- manual retry --------------------------------------------------------
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
      // Remove from queue if pending
      queueRef.current = queueRef.current.filter(item => item.idx !== idx)
      // Re-index remaining items in queue
      const removed = prev.filter((_, i) => i !== idx)
      queueRef.current = queueRef.current.map(item => ({
        ...item,
        idx: item.idx > idx ? item.idx - 1 : item.idx,
      }))
      return removed
    })
  }

  // ---- table edits ---------------------------------------------------------
  function editTag(photoIdx, tagIdx, field, value) {
    setPhotos(prev => prev.map((p, pi) => {
      if (pi !== photoIdx) return p
      const editedTags = p.editedTags.map((t, ti) => {
        if (ti !== tagIdx) return t
        const updated = { ...t, [field]: value }
        updated.seller_confirmed = fieldEdited(updated)
        return updated
      })
      return { ...p, editedTags }
    }))
  }

  // ---- derived state -------------------------------------------------------
  const allDone = photos.length > 0 && photos.every(p => p.status === 'done' || p.status === 'error')
  const allEditedTags = photos.flatMap(p => p.editedTags)
  const lowConfAbsent = allEditedTags
    .filter(t => !t.present && t.confidence < 0.75)
    .map(t => t.component_id)
  const untaggedAlways = [...ALWAYS_COMMON].filter(cid => !allEditedTags.some(t => t.component_id === cid))
  const unconfirmedCids = [...new Set([...lowConfAbsent, ...untaggedAlways])]

  // queue depth for status line
  const queueDepth = queueRef.current.length
  const taggingCount = photos.filter(p => p.status === 'tagging').length

  // ---- continue ------------------------------------------------------------
  function handleContinue() {
    const photoTagsForCapture = photos.flatMap(p =>
      p.rawTags.map(t => ({
        component_id: t.component_id,
        tag: t.condition !== 'unknown' ? t.condition : (t.present ? 'present' : 'not_present'),
        confidence: t.confidence,
        source_photo: t.source_photo || p.file.name,
      }))
    )

    const sellerConfirmedTags = []
    for (const t of allEditedTags) {
      const entry = { component_id: t.component_id }
      let hasEdit = false
      if (t.present !== t.orig_present)     { entry.present    = t.present;    hasEdit = true }
      if (t.condition !== t.orig_condition) { entry.condition  = t.condition;  hasEdit = true }
      if (t.severity  !== t.orig_severity)  { entry.severity   = t.severity;   hasEdit = true }
      if (t.seller_note.trim())             { entry.seller_note = t.seller_note.trim(); hasEdit = true }
      if (hasEdit) sellerConfirmedTags.push(entry)
    }

    const absencePresenceAnswers = Object.entries(unconfirmedAnswers).map(([cid, val]) => ({
      question_id: `P-UNCONFIRMED-${cid}`,
      component_id: cid,
      answer: val,
    }))

    onDone({ photoTagsForCapture, sellerConfirmedTags, absencePresenceAnswers })
  }

  // ---- render --------------------------------------------------------------
  return (
    <div>
      <h2 style={{ fontSize: 16, marginBottom: 8 }}>Upload Photos</h2>
      <p style={{ fontSize: 13, color: '#555', marginBottom: 16 }}>
        Label each photo with its room. Photos are sent one at a time and downscaled before upload.
        Vision tags condition only — you review and correct every field.
      </p>

      <input ref={inputRef} type="file" accept="image/*" multiple
        style={{ display: 'none' }} onChange={handleFiles} />
      <button style={btnStyle} onClick={() => inputRef.current.click()}>Add photos</button>

      {/* Queue status */}
      {(taggingCount > 0 || queueDepth > 0) && (
        <p style={{ fontSize: 12, color: '#555', marginTop: 8 }}>
          Tagging in progress — processing one at a time.
          {queueDepth > 0 && ` ${queueDepth} photo${queueDepth !== 1 ? 's' : ''} waiting in queue.`}
        </p>
      )}

      {photos.map((p, pi) => (
        <div key={pi} style={cardStyle}>
          <img src={p.url} alt={p.file.name} style={thumbStyle} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 6 }}>
              <span style={{ fontSize: 13, fontWeight: 500, wordBreak: 'break-all', flex: 1 }}>
                {p.file.name}
              </span>
              <button
                onClick={() => removePhoto(pi)}
                disabled={p.status === 'tagging'}
                title="Remove this photo"
                style={{ marginLeft: 8, fontSize: 11, color: '#c00', background: 'none', border: 'none', cursor: p.status === 'tagging' ? 'not-allowed' : 'pointer', flexShrink: 0, padding: '0 2px' }}>
                ✕ Remove
              </button>
            </div>

            <label style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
              Room:{' '}
              <select value={p.room_zone} onChange={e => setRoom(pi, e.target.value)}
                style={{ fontSize: 12 }} disabled={p.status === 'tagging'}>
                <option value="">— pick room —</option>
                {ROOM_ZONES.map(z => <option key={z.value} value={z.value}>{z.label}</option>)}
              </select>
            </label>

            {p.status === 'needs_room' && <span style={badge('gray')}>Pick a room to start tagging</span>}
            {p.status === 'tagging'    && <span style={badge('blue')}>Tagging… (downscaled, retries enabled)</span>}
            {p.status === 'error'      && (
              <div>
                <span style={{ color: '#c00', fontSize: 12 }}>
                  Failed after 3 attempts: {p.error}
                </span>
                <button style={{ marginLeft: 8, fontSize: 11, cursor: 'pointer' }}
                  onClick={() => retag(pi)}>
                  Retry
                </button>
              </div>
            )}

            {p.status === 'done' && (
              <div>
                <span style={badge('green')}>
                  {p.editedTags.length} component{p.editedTags.length !== 1 ? 's' : ''} detected
                </span>
                {p.editedTags.filter(t => t.seller_confirmed).length > 0 && (
                  <span style={{ ...badge('orange'), marginLeft: 6 }}>
                    {p.editedTags.filter(t => t.seller_confirmed).length} corrected
                  </span>
                )}
                <button style={{ marginLeft: 8, fontSize: 11, cursor: 'pointer' }}
                  onClick={() => retag(pi)}>
                  Re-tag
                </button>

                {p.editedTags.length === 0
                  ? <p style={{ fontSize: 12, color: '#888', marginTop: 4 }}>Nothing detected. Change room or re-tag.</p>
                  : (
                    <table style={tableStyle}>
                      <thead>
                        <tr>
                          <th style={th}>Component</th>
                          <th style={th}>Present</th>
                          <th style={th}>Condition <em style={{fontWeight:400}}>(vision draft)</em></th>
                          <th style={th}>Severity</th>
                          <th style={th}>Conf</th>
                          <th style={th}>Evidence (vision)</th>
                          <th style={th}>Your note</th>
                        </tr>
                      </thead>
                      <tbody>
                        {p.editedTags.map((t, ti) => (
                          <tr key={ti} style={{ background: t.seller_confirmed ? '#fffbe6' : 'transparent' }}>
                            <td style={td} title={t.component_id}>
                              {t.display_name || t.component_id}
                            </td>
                            <td style={td}>
                              <select style={cellSelect}
                                value={t.present ? 'yes' : 'no'}
                                onChange={e => editTag(pi, ti, 'present', e.target.value === 'yes')}>
                                <option value="yes">yes</option>
                                <option value="no">no</option>
                              </select>
                            </td>
                            <td style={td}>
                              <select style={cellSelect} value={t.condition}
                                onChange={e => editTag(pi, ti, 'condition', e.target.value)}>
                                {CONDITIONS.map(c => <option key={c} value={c}>{c}</option>)}
                              </select>
                            </td>
                            <td style={td}>
                              <select style={cellSelect} value={t.severity}
                                onChange={e => editTag(pi, ti, 'severity', e.target.value)}>
                                {SEVERITIES.map(s => <option key={s} value={s}>{s}</option>)}
                              </select>
                            </td>
                            <td style={{ ...td, fontSize: 11, color: t.seller_confirmed ? '#b45309' : '#555' }}>
                              {t.seller_confirmed ? 'seller-confirmed' : `${(t.confidence*100).toFixed(0)}%`}
                            </td>
                            <td style={{ ...td, fontSize: 11, color: '#777', maxWidth: 180 }}>{t.evidence}</td>
                            <td style={td}>
                              <input type="text" style={{ fontSize: 11, width: 130 }}
                                placeholder="optional note"
                                value={t.seller_note}
                                onChange={e => editTag(pi, ti, 'seller_note', e.target.value)} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
              </div>
            )}
          </div>
        </div>
      ))}

      {/* Unconfirmed-absence panel */}
      {allDone && unconfirmedCids.length > 0 && (
        <div style={{ border: '1px solid #ffc107', borderRadius: 4, padding: 14, marginTop: 16, background: '#fffbe6' }}>
          <strong style={{ fontSize: 13 }}>Components we couldn't confirm ({unconfirmedCids.length})</strong>
          <p style={{ fontSize: 12, color: '#666', margin: '4px 0 10px' }}>
            Vision didn't detect these, or detected them with low confidence. Does the home have them?
          </p>
          {unconfirmedCids.map(cid => (
            <div key={cid} style={{ marginBottom: 8, fontSize: 13 }}>
              <code style={{ fontSize: 11 }}>{cid}</code>
              {' — '}
              <label style={{ marginRight: 12 }}>
                <input type="radio" name={`unc_${cid}`} value="yes"
                  checked={unconfirmedAnswers[cid] === 'yes'}
                  onChange={() => setUnconfirmedAnswers(p => ({ ...p, [cid]: 'yes' }))} />
                {' '}yes
              </label>
              <label style={{ marginRight: 12 }}>
                <input type="radio" name={`unc_${cid}`} value="no"
                  checked={unconfirmedAnswers[cid] === 'no'}
                  onChange={() => setUnconfirmedAnswers(p => ({ ...p, [cid]: 'no' }))} />
                {' '}no
              </label>
              <label>
                <input type="radio" name={`unc_${cid}`} value="unsure"
                  checked={unconfirmedAnswers[cid] === 'unsure'}
                  onChange={() => setUnconfirmedAnswers(p => ({ ...p, [cid]: 'unsure' }))} />
                {' '}not sure
              </label>
            </div>
          ))}
        </div>
      )}

      <div style={{ marginTop: 20 }}>
        {photos.length === 0 && (
          <button style={{ ...btnStyle, background: '#eee', marginRight: 8 }}
            onClick={() => onDone({ photoTagsForCapture: [], sellerConfirmedTags: [], absencePresenceAnswers: [] })}>
            Skip photos
          </button>
        )}
        {allDone && (
          <button style={btnStyle} onClick={handleContinue}>
            Continue to questionnaire
          </button>
        )}
        {photos.length > 0 && !allDone && (
          <p style={{ fontSize: 13, color: '#888', marginTop: 8 }}>
            Waiting for all photos to finish tagging…
          </p>
        )}
      </div>
    </div>
  )
}

const btnStyle    = { padding: '8px 20px', fontSize: 14, cursor: 'pointer' }
const cardStyle   = { display: 'flex', gap: 12, marginTop: 16, padding: 12, border: '1px solid #ddd', borderRadius: 4 }
const thumbStyle  = { width: 80, height: 80, objectFit: 'cover', borderRadius: 2, flexShrink: 0 }
const tableStyle  = { borderCollapse: 'collapse', width: '100%', fontSize: 12, marginTop: 8 }
const th          = { textAlign: 'left', padding: '3px 6px', borderBottom: '1px solid #ccc', fontWeight: 600, whiteSpace: 'nowrap' }
const td          = { padding: '3px 6px', borderBottom: '1px solid #eee', verticalAlign: 'middle' }
const cellSelect  = { fontSize: 11, padding: '1px 2px' }
const badge = (color) => ({
  display: 'inline-block', fontSize: 11, padding: '1px 7px', borderRadius: 10, marginBottom: 6,
  background: color === 'green' ? '#d4edda' : color === 'blue' ? '#cce5ff' : color === 'orange' ? '#fff3cd' : '#eee',
  color:      color === 'green' ? '#155724' : color === 'blue' ? '#004085' : color === 'orange' ? '#856404' : '#555',
})
