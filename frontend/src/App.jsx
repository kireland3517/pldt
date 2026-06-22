import React, { useState, useEffect } from 'react'
import AddressStep from './components/AddressStep'
import PhotoStep from './components/PhotoStep'
import QuestionnaireStep from './components/QuestionnaireStep'
import ResultsStep from './components/ResultsStep'

const STEPS = ['address', 'photos', 'questionnaire', 'results']

export default function App() {
  const [step, setStep] = useState('address')
  const [sessionId, setSessionId] = useState(null)
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
        <AddressStep onDone={handleSessionCreated} />
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
