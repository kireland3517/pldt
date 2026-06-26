import React, { useState, useEffect } from 'react'
import AddressStep from './components/AddressStep'
import PhotoStep from './components/PhotoStep'
import QuestionnaireStep from './components/QuestionnaireStep'
import ResultsStep from './components/ResultsStep'

const STEPS = ['address', 'photos', 'questionnaire', 'results']

export default function App() {
  const [step, setStep] = useState('address')
  const [sessionId, setSessionId] = useState(null)
  const [resumeInput, setResumeInput] = useState('')
  const [photoData, setPhotoData] = useState({
    photoTagsForCapture: [],
    sellerConfirmedTags: [],
    absencePresenceAnswers: [],
  })

  // On load: resume from URL ?session=<id> so page refresh doesn't lose the session
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const sid = params.get('session')
    const s   = params.get('step')
    if (sid) {
      setSessionId(sid)
      setStep(STEPS.includes(s) ? s : 'photos')
    }
  }, [])

  function next(current) {
    const nextStep = STEPS[STEPS.indexOf(current) + 1]
    setStep(nextStep)
    // Keep URL in sync so the user can bookmark or refresh mid-flow
    if (sessionId) {
      const url = new URL(window.location)
      url.searchParams.set('step', nextStep)
      window.history.replaceState({}, '', url)
    }
  }

  function handleSessionCreated(sid) {
    setSessionId(sid)
    // Write session to URL immediately so refresh resumes here
    const url = new URL(window.location)
    url.searchParams.set('session', sid)
    url.searchParams.set('step', 'photos')
    window.history.replaceState({}, '', url)
    next('address')
  }

  function handleResume() {
    const sid = resumeInput.trim()
    if (!sid) return
    setSessionId(sid)
    setStep('results')
    const url = new URL(window.location)
    url.searchParams.set('session', sid)
    url.searchParams.set('step', 'results')
    window.history.replaceState({}, '', url)
  }

  return (
    <div style={{ maxWidth: 760, margin: '0 auto', padding: '24px 16px', fontFamily: 'system-ui, sans-serif' }}>
      <h1 style={{ fontSize: 20, marginBottom: 4 }}>Pre-Listing Decision Tool</h1>
      <nav style={{ marginBottom: 24, fontSize: 13, color: '#666' }}>
        {STEPS.map((s, i) => (
          <span key={s}>
            <span style={{ fontWeight: s === step ? 700 : 400, color: s === step ? '#000' : '#aaa' }}>
              {i + 1}. {s.charAt(0).toUpperCase() + s.slice(1)}
            </span>
            {i < STEPS.length - 1 && <span style={{ margin: '0 6px', color: '#ccc' }}>›</span>}
          </span>
        ))}
      </nav>

      {step === 'address' && (
        <div>
          <div style={{ background: '#f0f9ff', border: '1px solid #bae6fd', borderRadius: 4,
                        padding: '12px 16px', marginBottom: 20 }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6, color: '#0369a1' }}>
              Resume an existing session
            </div>
            <div style={{ fontSize: 12, color: '#555', marginBottom: 8 }}>
              Paste a session ID to jump straight to your results — no re-upload needed.
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <input
                type='text'
                placeholder='Session ID (e.g. 3f7a…)'
                value={resumeInput}
                onChange={e => setResumeInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleResume()}
                style={{ flex: 1, padding: '5px 8px', fontSize: 13, border: '1px solid #93c5fd', borderRadius: 3 }}
              />
              <button onClick={handleResume}
                style={{ padding: '5px 14px', fontSize: 13, cursor: 'pointer',
                         background: '#0369a1', color: '#fff', border: 'none', borderRadius: 3 }}>
                Go to results
              </button>
            </div>
          </div>
          <div style={{ fontSize: 12, color: '#999', marginBottom: 12 }}>— or start a new session —</div>
          <AddressStep onDone={handleSessionCreated} />
        </div>
      )}
      {step === 'photos' && (
        <PhotoStep
          sessionId={sessionId}
          onDone={(data) => { setPhotoData(data); next('photos') }}
        />
      )}
      {step === 'questionnaire' && (
        <QuestionnaireStep
          sessionId={sessionId}
          photoData={photoData}
          onDone={() => next('questionnaire')}
        />
      )}
      {step === 'results' && (
        <ResultsStep sessionId={sessionId} />
      )}
    </div>
  )
}
