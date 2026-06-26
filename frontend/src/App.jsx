import React, { useState, useEffect } from 'react'
import AddressStep from './components/AddressStep'
import PhotoStep from './components/PhotoStep'
import QuestionnaireStep from './components/QuestionnaireStep'
import ResultsStep from './components/ResultsStep'
import { listSessions } from './api'

const STEPS = ['home', 'address', 'photos', 'questionnaire', 'results']

function fmt(n) {
  if (n == null) return null
  return '$' + Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 })
}

function fmtDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function SessionPicker({ onSelect, onNew }) {
  const [sessions, setSessions] = useState(null)
  const [error, setError]       = useState(null)

  useEffect(() => {
    listSessions(30)
      .then(r => setSessions(r.sessions))
      .catch(e => setError(e.message))
  }, [])

  const withResults = (sessions || []).filter(s => s.has_results)
  const inProgress  = (sessions || []).filter(s => !s.has_results)

  return (
    <div>
      <h2 style={{ fontSize: 16, marginTop: 0, marginBottom: 4 }}>Pre-Listing Decision Tool</h2>

      {sessions === null && !error && (
        <p style={{ color: '#888', fontSize: 13 }}>Loading sessions…</p>
      )}
      {error && (
        <p style={{ color: '#c00', fontSize: 13 }}>Could not load sessions: {error}</p>
      )}

      {sessions !== null && withResults.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
            Previous reports — click to open
          </div>
          <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13 }}>
            <thead>
              <tr style={{ background: '#f5f5f5' }}>
                <th style={th}>Address</th>
                <th style={th}>Date</th>
                <th style={th}>Est. net (recommended)</th>
                <th style={{ ...th, width: 80 }}></th>
              </tr>
            </thead>
            <tbody>
              {withResults.map((s, i) => (
                <tr key={s.id}
                    style={{ background: i % 2 === 0 ? '#fff' : '#fafafa', cursor: 'pointer' }}
                    onClick={() => onSelect(s.id)}>
                  <td style={td}><strong>{s.address || '—'}</strong></td>
                  <td style={{ ...td, color: '#666' }}>{fmtDate(s.created_at)}</td>
                  <td style={{ ...td, color: s.net < 0 ? '#c00' : '#1a7f37', fontWeight: 600 }}>
                    {fmt(s.net) ?? '—'}
                  </td>
                  <td style={{ ...td, textAlign: 'right' }}>
                    <button
                      onClick={e => { e.stopPropagation(); onSelect(s.id) }}
                      style={{ fontSize: 12, padding: '3px 10px', cursor: 'pointer',
                               background: '#1a1a1a', color: '#fff',
                               border: 'none', borderRadius: 3 }}>
                      Open →
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {sessions !== null && inProgress.length > 0 && (
        <details style={{ marginBottom: 20 }}>
          <summary style={{ fontSize: 12, color: '#888', cursor: 'pointer' }}>
            {inProgress.length} incomplete session{inProgress.length !== 1 ? 's' : ''}
          </summary>
          <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 12, marginTop: 6 }}>
            <tbody>
              {inProgress.map((s, i) => (
                <tr key={s.id} style={{ background: i % 2 === 0 ? '#fff' : '#fafafa' }}>
                  <td style={td}>{s.address || '—'}</td>
                  <td style={{ ...td, color: '#888' }}>{fmtDate(s.created_at)}</td>
                  <td style={{ ...td, color: '#888' }}>{s.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      {sessions !== null && sessions.length === 0 && (
        <p style={{ color: '#888', fontSize: 13, marginBottom: 16 }}>
          No sessions yet. Start one below.
        </p>
      )}

      <div style={{ borderTop: '1px solid #e5e7eb', paddingTop: 20, marginTop: 4 }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10, color: '#555' }}>
          Start a new session
        </div>
        <button
          onClick={onNew}
          style={{ padding: '8px 20px', fontSize: 13, cursor: 'pointer',
                   background: '#fff', border: '1px solid #ccc', borderRadius: 3 }}>
          + New property
        </button>
      </div>
    </div>
  )
}

const th = { textAlign: 'left', padding: '6px 10px', fontWeight: 600,
             borderBottom: '1px solid #e5e7eb', whiteSpace: 'nowrap' }
const td = { padding: '8px 10px', borderBottom: '1px solid #f0f0f0', verticalAlign: 'middle' }

export default function App() {
  const [step,      setStep]      = useState('home')
  const [sessionId, setSessionId] = useState(null)
  const [photoData, setPhotoData] = useState({
    photoTagsForCapture: [], sellerConfirmedTags: [], absencePresenceAnswers: [],
  })

  // Resume from URL ?session=<id>&step=<step>
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const sid = params.get('session')
    const s   = params.get('step')
    if (sid) {
      setSessionId(sid)
      setStep(STEPS.includes(s) ? s : 'results')
    }
  }, [])

  function syncUrl(sid, s) {
    const url = new URL(window.location)
    if (sid) url.searchParams.set('session', sid)
    url.searchParams.set('step', s)
    window.history.replaceState({}, '', url)
  }

  function openSession(sid) {
    setSessionId(sid)
    setStep('results')
    syncUrl(sid, 'results')
  }

  function handleSessionCreated(sid) {
    setSessionId(sid)
    syncUrl(sid, 'photos')
    setStep('photos')
  }

  function next(current) {
    const nextStep = STEPS[STEPS.indexOf(current) + 1]
    setStep(nextStep)
    syncUrl(sessionId, nextStep)
  }

  return (
    <div style={{ maxWidth: 760, margin: '0 auto', padding: '24px 16px', fontFamily: 'system-ui, sans-serif' }}>

      {step !== 'home' && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
            <h1 style={{ fontSize: 18, margin: 0 }}>Pre-Listing Decision Tool</h1>
            <button onClick={() => { setStep('home'); syncUrl(null, 'home') }}
              style={{ fontSize: 12, color: '#888', background: 'none', border: 'none',
                       cursor: 'pointer', textDecoration: 'underline' }}>
              ← All sessions
            </button>
          </div>
          <nav style={{ marginBottom: 20, fontSize: 13, color: '#666' }}>
            {['photos', 'questionnaire', 'results'].map((s, i) => (
              <span key={s}>
                <span style={{ fontWeight: s === step ? 700 : 400, color: s === step ? '#000' : '#aaa' }}>
                  {i + 1}. {s.charAt(0).toUpperCase() + s.slice(1)}
                </span>
                {i < 2 && <span style={{ margin: '0 6px', color: '#ccc' }}>›</span>}
              </span>
            ))}
          </nav>
        </>
      )}

      {step === 'home' && (
        <SessionPicker onSelect={openSession} onNew={() => setStep('address')} />
      )}
      {step === 'address' && (
        <AddressStep onDone={handleSessionCreated} />
      )}
      {step === 'photos' && (
        <PhotoStep sessionId={sessionId}
          onDone={data => { setPhotoData(data); next('photos') }} />
      )}
      {step === 'questionnaire' && (
        <QuestionnaireStep sessionId={sessionId} photoData={photoData}
          onDone={() => next('questionnaire')} />
      )}
      {step === 'results' && (
        <ResultsStep sessionId={sessionId} />
      )}
    </div>
  )
}
