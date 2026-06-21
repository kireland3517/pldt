import React, { useState, useEffect } from 'react'
import { getQuestions, submitCapture } from '../api'

// These are always asked regardless of vision (photos can't show odor, crawlspace interior)
const ALWAYS_ASK_CONDITION = new Set(['Q-SMOKE-1', 'Q-CRAWL-1', 'Q-ELEC-1'])

function buildTagMap(photoTags) {
  const map = {}
  for (const tag of photoTags) {
    if (!map[tag.component_id] || tag.confidence > map[tag.component_id].confidence) {
      map[tag.component_id] = tag
    }
  }
  return map
}

// Build set of component_ids that vision OR absence-panel confirmed as present
function buildPresentSet(photoTagsForCapture, absencePresenceAnswers) {
  const present = new Set()
  for (const t of photoTagsForCapture) {
    if (t.confidence >= 0.5) present.add(t.component_id)
  }
  for (const a of absencePresenceAnswers) {
    if (a.answer === 'yes') present.add(a.component_id)
  }
  return present
}

export default function QuestionnaireStep({ sessionId, photoData, onDone }) {
  const [qBank, setQBank]       = useState(null)
  const [answers, setAnswers]   = useState({})
  const [loading, setLoading]   = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError]       = useState(null)

  const { photoTagsForCapture = [], sellerConfirmedTags = [], absencePresenceAnswers = [] } = photoData

  useEffect(() => {
    getQuestions(sessionId)
      .then(setQBank)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [sessionId])

  function answer(key, value) {
    setAnswers(prev => ({ ...prev, [key]: value }))
  }

  async function submit(e) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)

    try {
      if (!qBank) throw new Error('Questions not loaded.')

      const tagMap      = buildTagMap(photoTagsForCapture)
      const presentSet  = buildPresentSet(photoTagsForCapture, absencePresenceAnswers)

      // Presence answers from questionnaire
      const presenceAnswers = []
      for (const q of qBank.presence_questions) {
        const key = `P_${q.question_id}`
        const val = answers[key]
        if (val) {
          const cids = Array.isArray(q.maps_to) ? q.maps_to : [q.maps_to].filter(Boolean)
          for (const cid of cids) {
            presenceAnswers.push({ question_id: q.question_id, component_id: cid, answer: val })
          }
        }
      }

      // Condition answers from questionnaire
      const conditionAnswers = []
      for (const q of qBank.condition_questions) {
        const key = `C_${q.question_id}`
        const val = answers[key]
        if (val) {
          const cids = Array.isArray(q.maps_to) ? q.maps_to : [q.maps_to].filter(Boolean)
          for (const cid of cids) {
            conditionAnswers.push({ question_id: q.question_id, component_id: cid, answer: val })
          }
        }
      }

      // Constraints → seller_inputs
      const sellerInputs = {}
      if (answers['C-PAYOFF'])   sellerInputs.mortgage_balance  = parseFloat(answers['C-PAYOFF']) || 0
      if (answers['C-TIMELINE']) sellerInputs.timeline          = answers['C-TIMELINE']
      if (answers['C-FUND-1'])   sellerInputs.can_fund_upfront  = answers['C-FUND-1'] === 'yes'

      await submitCapture(sessionId, {
        photoTagsForCapture,
        sellerConfirmedTags,
        absencePresenceAnswers,
        presence_answers:  presenceAnswers,
        condition_answers: conditionAnswers,
        seller_inputs:     sellerInputs,
      })

      onDone()
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) return <p>Loading questions...</p>
  if (!qBank)  return <p style={{ color: 'red' }}>Failed to load questionnaire. {error}</p>

  const tagMap     = buildTagMap(photoTagsForCapture)
  const presentSet = buildPresentSet(photoTagsForCapture, absencePresenceAnswers)

  // Presence questions: show all. Pre-fill where vision was confident.
  const presenceQs = qBank.presence_questions

  // Condition questions:
  // Show if: always-ask, OR the component is in presentSet (vision/absence confirmed),
  // OR the seller explicitly confirmed it present in their table edits.
  // NOTE: we do NOT skip based on vision saying "good" — seller must answer
  //       about datedness and subtle defects regardless of vision's draft.
  const sellerConfirmedPresent = new Set(
    sellerConfirmedTags.filter(t => t.present === true).map(t => t.component_id)
  )
  const conditionQs = qBank.condition_questions.filter(q => {
    if (ALWAYS_ASK_CONDITION.has(q.question_id)) return true
    const cids = Array.isArray(q.maps_to) ? q.maps_to : [q.maps_to].filter(Boolean)
    return cids.some(cid =>
      presentSet.has(cid) ||
      sellerConfirmedPresent.has(cid) ||
      answers[`P_${q.question_id.replace('Q-', 'P-')}`] === 'yes'
    )
  })

  // Vision pre-fills for display (shown as suggestions, not locked)
  function visionSuggestion(cid) {
    const t = tagMap[cid]
    if (!t || t.confidence < 0.5) return null
    return `Vision: ${t.condition} (${(t.confidence * 100).toFixed(0)}% conf)`
  }

  return (
    <form onSubmit={submit}>
      <h2 style={{ fontSize: 16, marginBottom: 8 }}>Questionnaire</h2>
      <p style={{ fontSize: 13, color: '#555', marginBottom: 20 }}>
        Your answers override vision. Vision's draft is shown as a suggestion only.
      </p>

      {/* Presence */}
      <section style={sectionStyle}>
        <h3 style={h3}>What does your home have?</h3>
        {presenceQs.map(q => {
          const cid = Array.isArray(q.maps_to) ? q.maps_to[0] : q.maps_to
          const suggestion = cid ? visionSuggestion(cid) : null
          return (
            <QuestionRow
              key={q.question_id}
              q={q}
              prefix="P"
              answers={answers}
              onAnswer={answer}
              suggestion={suggestion}
            />
          )
        })}
      </section>

      {/* Condition */}
      {conditionQs.length > 0 && (
        <section style={sectionStyle}>
          <h3 style={h3}>Condition — what you know or can check</h3>
          <p style={{ fontSize: 12, color: '#777', marginTop: -8, marginBottom: 12 }}>
            Vision's assessment is a draft. Answer these regardless of what vision detected.
          </p>
          {conditionQs.map(q => {
            const cid = Array.isArray(q.maps_to) ? q.maps_to[0] : q.maps_to
            const suggestion = cid ? visionSuggestion(cid) : null
            return (
              <QuestionRow
                key={q.question_id}
                q={q}
                prefix="C"
                answers={answers}
                onAnswer={answer}
                suggestion={suggestion}
              />
            )
          })}
        </section>
      )}

      {/* Constraints */}
      <section style={sectionStyle}>
        <h3 style={h3}>Your situation</h3>
        {qBank.constraints_intake.map(q => (
          <QuestionRow key={q.question_id} q={q} prefix="CI" answers={answers} onAnswer={answer} />
        ))}
      </section>

      {error && <p style={{ color: 'red', marginBottom: 8 }}>{error}</p>}
      <button style={btnStyle} type="submit" disabled={submitting}>
        {submitting ? 'Submitting...' : 'Submit and see report'}
      </button>
    </form>
  )
}

function QuestionRow({ q, prefix, answers, onAnswer, suggestion }) {
  const key = `${prefix}_${q.question_id}`
  const val = answers[key] ?? ''

  return (
    <div style={{ marginBottom: 16 }}>
      <label style={{ fontSize: 13, fontWeight: 500, display: 'block', marginBottom: 3 }}>
        {q.prompt}
      </label>
      {suggestion && (
        <div style={{ fontSize: 11, color: '#888', marginBottom: 4, fontStyle: 'italic' }}>
          {suggestion}
        </div>
      )}
      {q.answer_type === 'yes_no' && (
        <div>
          {['yes', 'no'].map(opt => (
            <label key={opt} style={{ marginRight: 16, fontSize: 13 }}>
              <input type="radio" name={key} value={opt}
                checked={val === opt} onChange={() => onAnswer(key, opt)} />
              {' '}{opt}
            </label>
          ))}
        </div>
      )}
      {q.answer_type === 'single_select' && (
        <select style={selectStyle} value={val} onChange={e => onAnswer(key, e.target.value)}>
          <option value="">— select —</option>
          {(q.options || []).map(o => <option key={o} value={o}>{o}</option>)}
        </select>
      )}
      {q.answer_type === 'range' && (
        <input type="number" style={selectStyle} placeholder="$0"
          value={val} onChange={e => onAnswer(key, e.target.value)} />
      )}
    </div>
  )
}

const btnStyle    = { padding: '8px 20px', fontSize: 14, cursor: 'pointer' }
const sectionStyle= { marginBottom: 24, paddingBottom: 16, borderBottom: '1px solid #eee' }
const h3          = { fontSize: 14, marginTop: 0, marginBottom: 14 }
const selectStyle = { fontSize: 13, padding: '4px 6px' }
