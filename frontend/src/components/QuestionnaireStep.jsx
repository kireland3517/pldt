import React, { useState, useEffect } from 'react'
import { getQuestions, submitCapture } from '../api'

// Components photos can't show -- always ask these presence questions
const ALWAYS_ASK_PRESENCE = new Set(['P-CRAWL', 'P-HVAC-AGE', 'P-WH-AGE', 'P-ROOF-AGE', 'P-ELEC'])

// Condition questions always asked regardless of vision (photo can't show odor, crawlspace interior, etc.)
const ALWAYS_ASK_CONDITION = new Set(['Q-SMOKE-1', 'Q-CRAWL-1', 'Q-ELEC-1'])

function buildTagMap(photoTags) {
  const map = {}
  for (const tag of photoTags) {
    const cid = tag.component_id
    if (!map[cid] || tag.confidence > map[cid].confidence) {
      map[cid] = tag
    }
  }
  return map
}

function narrowPresence(presenceQuestions, tagMap) {
  return presenceQuestions.map(q => {
    if (ALWAYS_ASK_PRESENCE.has(q.question_id)) return { ...q, prefill: null, fromVision: false }
    const cid = Array.isArray(q.maps_to) ? q.maps_to[0] : q.maps_to
    const tag = cid ? tagMap[cid] : null
    if (tag && tag.confidence >= 0.75) {
      return { ...q, prefill: tag.present ? 'yes' : 'no', fromVision: true, visionEvidence: tag.evidence }
    }
    return { ...q, prefill: null, fromVision: false }
  })
}

function narrowCondition(conditionQuestions, answers, tagMap) {
  // Show a condition question if:
  // 1. It's always asked, OR
  // 2. The component it maps to was answered present
  return conditionQuestions.filter(q => {
    if (ALWAYS_ASK_CONDITION.has(q.question_id)) return true
    const cid = q.maps_to
    if (!cid) return true
    // Check presence answers
    const presenceAnswer = answers[`presence_${cid}`]
    if (presenceAnswer === 'yes') return true
    // Check vision pre-filled present
    const tag = tagMap[cid]
    if (tag && tag.present && tag.confidence >= 0.75) return true
    return false
  })
}

export default function QuestionnaireStep({ sessionId, photoTags, onDone }) {
  const [qBank, setQBank] = useState(null)
  const [answers, setAnswers] = useState({})
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    getQuestions(sessionId).then(setQBank).catch(e => setError(e.message)).finally(() => setLoading(false))
  }, [sessionId])

  function answer(key, value) {
    setAnswers(prev => ({ ...prev, [key]: value }))
  }

  async function submit(e) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)

    try {
      // Build capture payload from answers + photo tags
      const tagMap = buildTagMap(photoTags)

      // Presence answers
      const presenceAnswers = []
      if (qBank) {
        for (const q of qBank.presence_questions) {
          const key = `presence_${q.question_id}`
          const val = answers[key] ?? (narrowPresence([q], tagMap)[0].prefill)
          if (val != null) {
            const cids = Array.isArray(q.maps_to) ? q.maps_to : [q.maps_to].filter(Boolean)
            for (const cid of cids) {
              presenceAnswers.push({ question_id: q.question_id, component_id: cid, answer: val })
            }
          }
        }
      }

      // Condition answers
      const conditionAnswers = []
      if (qBank) {
        for (const q of qBank.condition_questions) {
          const key = `condition_${q.question_id}`
          if (answers[key]) {
            const cids = Array.isArray(q.maps_to) ? q.maps_to : [q.maps_to].filter(Boolean)
            for (const cid of cids) {
              conditionAnswers.push({ question_id: q.question_id, component_id: cid, answer: answers[key] })
            }
          }
        }
      }

      // Constraints
      const sellerInputs = {}
      if (answers['C-PAYOFF'])   sellerInputs.mortgage_balance = parseFloat(answers['C-PAYOFF']) || 0
      if (answers['C-TIMELINE']) sellerInputs.timeline = answers['C-TIMELINE']
      if (answers['C-FUND-1'])   sellerInputs.can_fund_upfront = answers['C-FUND-1'] === 'yes'

      await submitCapture(sessionId, {
        has_inspection_report: false,
        photo_tags: photoTags,
        presence_answers: presenceAnswers,
        condition_answers: conditionAnswers,
        seller_inputs: sellerInputs,
      })

      onDone()
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) return <p>Loading questions...</p>
  if (!qBank) return <p style={{ color: 'red' }}>Failed to load questionnaire.</p>

  const tagMap = buildTagMap(photoTags)
  const presenceQs = narrowPresence(qBank.presence_questions, tagMap)
  const conditionQs = narrowCondition(qBank.condition_questions, answers, tagMap)

  const visionFilled = presenceQs.filter(q => q.fromVision)
  const needsAnswer  = presenceQs.filter(q => !q.fromVision)

  return (
    <form onSubmit={submit}>
      <h2 style={{ fontSize: 16, marginBottom: 8 }}>Questionnaire</h2>

      {visionFilled.length > 0 && (
        <div style={{ background: '#f0f8ff', border: '1px solid #cce5ff', borderRadius: 4, padding: 12, marginBottom: 20 }}>
          <strong style={{ fontSize: 13 }}>Pre-filled by vision ({visionFilled.length})</strong>
          <p style={{ fontSize: 12, color: '#555', margin: '4px 0 8px' }}>
            These were detected in your photos with high confidence. You can override below.
          </p>
          {visionFilled.map(q => (
            <div key={q.question_id} style={{ marginBottom: 8 }}>
              <label style={{ fontSize: 13 }}>
                <strong>{q.prompt}</strong>
                <span style={{ marginLeft: 8, color: '#155724', fontSize: 12 }}>
                  Vision: {q.prefill} — {q.visionEvidence}
                </span>
                <select
                  style={{ marginLeft: 8 }}
                  value={answers[`presence_${q.question_id}`] ?? q.prefill}
                  onChange={e => answer(`presence_${q.question_id}`, e.target.value)}
                >
                  {q.answer_type === 'yes_no'
                    ? [<option key="y" value="yes">yes</option>, <option key="n" value="no">no</option>]
                    : (q.options || []).map(o => <option key={o} value={o}>{o}</option>)
                  }
                </select>
              </label>
            </div>
          ))}
        </div>
      )}

      {needsAnswer.length > 0 && (
        <section style={{ marginBottom: 24 }}>
          <h3 style={{ fontSize: 14, marginBottom: 12 }}>Presence — what does your home have?</h3>
          {needsAnswer.map(q => <QuestionRow key={q.question_id} q={q} prefix="presence" answers={answers} onAnswer={answer} />)}
        </section>
      )}

      {conditionQs.length > 0 && (
        <section style={{ marginBottom: 24 }}>
          <h3 style={{ fontSize: 14, marginBottom: 12 }}>Condition — what you can see or know</h3>
          {conditionQs.map(q => <QuestionRow key={q.question_id} q={q} prefix="condition" answers={answers} onAnswer={answer} />)}
        </section>
      )}

      <section style={{ marginBottom: 24 }}>
        <h3 style={{ fontSize: 14, marginBottom: 12 }}>Your situation</h3>
        {qBank.constraints_intake.map(q => <QuestionRow key={q.question_id} q={q} prefix="" answers={answers} onAnswer={answer} />)}
      </section>

      {error && <p style={{ color: 'red' }}>{error}</p>}

      <button style={btnStyle} type="submit" disabled={submitting}>
        {submitting ? 'Submitting...' : 'Submit and see report'}
      </button>
    </form>
  )
}

function QuestionRow({ q, prefix, answers, onAnswer }) {
  const key = prefix ? `${prefix}_${q.question_id}` : q.question_id
  const val = answers[key] ?? ''

  return (
    <div style={{ marginBottom: 14 }}>
      <label style={{ fontSize: 13, fontWeight: 500, display: 'block', marginBottom: 4 }}>
        {q.prompt}
      </label>
      {q.answer_type === 'yes_no' && (
        <div>
          {['yes', 'no'].map(opt => (
            <label key={opt} style={{ marginRight: 16, fontSize: 13 }}>
              <input type="radio" name={key} value={opt} checked={val === opt} onChange={() => onAnswer(key, opt)} />
              {' '}{opt}
            </label>
          ))}
        </div>
      )}
      {(q.answer_type === 'single_select') && (
        <select style={selectStyle} value={val} onChange={e => onAnswer(key, e.target.value)}>
          <option value="">— select —</option>
          {(q.options || []).map(o => <option key={o} value={o}>{o}</option>)}
        </select>
      )}
      {q.answer_type === 'range' && (
        <input
          type="number"
          style={selectStyle}
          placeholder="$0"
          value={val}
          onChange={e => onAnswer(key, e.target.value)}
        />
      )}
    </div>
  )
}

const btnStyle    = { padding: '8px 20px', fontSize: 14, cursor: 'pointer' }
const selectStyle = { fontSize: 13, padding: '4px 6px' }
