import React, { useState } from 'react'
import AddressStep from './components/AddressStep'
import PhotoStep from './components/PhotoStep'
import QuestionnaireStep from './components/QuestionnaireStep'
import ResultsStep from './components/ResultsStep'

const STEPS = ['address', 'photos', 'questionnaire', 'results']

export default function App() {
  const [step, setStep] = useState('address')
  const [sessionId, setSessionId] = useState(null)
  const [photoTags, setPhotoTags] = useState([])   // all tags from all photos

  function next(s) { setStep(STEPS[STEPS.indexOf(s) + 1]) }

  return (
    <div style={{ maxWidth: 720, margin: '0 auto', padding: '24px 16px', fontFamily: 'system-ui, sans-serif' }}>
      <h1 style={{ fontSize: 20, marginBottom: 4 }}>Pre-Listing Decision Tool</h1>
      <nav style={{ marginBottom: 24, fontSize: 13, color: '#666' }}>
        {STEPS.map((s, i) => (
          <span key={s}>
            <span style={{ fontWeight: s === step ? 700 : 400, color: s === step ? '#000' : '#888' }}>
              {i + 1}. {s.charAt(0).toUpperCase() + s.slice(1)}
            </span>
            {i < STEPS.length - 1 && <span style={{ margin: '0 6px' }}>{'>'}</span>}
          </span>
        ))}
      </nav>

      {step === 'address' && (
        <AddressStep
          onDone={(sid) => { setSessionId(sid); next('address') }}
        />
      )}
      {step === 'photos' && (
        <PhotoStep
          sessionId={sessionId}
          onDone={(tags) => { setPhotoTags(tags); next('photos') }}
        />
      )}
      {step === 'questionnaire' && (
        <QuestionnaireStep
          sessionId={sessionId}
          photoTags={photoTags}
          onDone={() => next('questionnaire')}
        />
      )}
      {step === 'results' && (
        <ResultsStep sessionId={sessionId} />
      )}
    </div>
  )
}
