import React, { useState, useEffect } from 'react'
import { getQuestions, submitCapture } from '../api'

// Always ask these regardless of vision — photos can't show odor, panel access, etc.
const ALWAYS_ASK = new Set(['Q-SMOKE-1', 'Q-ELEC-1'])

function buildTagMap(photoTags) {
  const map = {}
  for (const tag of photoTags) {
    if (!map[tag.component_id] || tag.confidence > map[tag.component_id].confidence) {
      map[tag.component_id] = tag
    }
  }
  return map
}

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

// ── branching engine ──────────────────────────────────────────────────────────
//
// A question is visible if:
//   (a) It is a branch target of another question → parent must be visible
//       AND answered with the value that points to this question.
//   (b) It is not a branch target → evaluate its `triggers` field:
//       - starts with "intake_condition" → always show
//       - contains component IDs (e.g. "DECK-01 present") → any of those
//         component IDs must be in presentSet or sellerConfirmedPresent
//
// Branches whose values are action strings (e.g. "force_replace", "not_floor")
// rather than question IDs are terminal — they don't gate any follow-up.

function isVisible(q, allQs, presentSet, answers, sellerConfirmedPresent, prefix) {
  // Find if any other question's branches point to this one
  let parentQ = null
  let triggeringAnswer = null
  for (const pq of allQs) {
    for (const [ans, target] of Object.entries(pq.branches || {})) {
      if (target === q.question_id) {
        parentQ = pq
        triggeringAnswer = ans
        break
      }
    }
    if (parentQ) break
  }

  if (parentQ) {
    // Branch target: parent must be visible AND answered with the triggering value
    if (!isVisible(parentQ, allQs, presentSet, answers, sellerConfirmedPresent, prefix)) {
      return false
    }
    return answers[`${prefix}_${parentQ.question_id}`] === triggeringAnswer
  }

  // Not a branch target — evaluate trigger directly
  const trigger = q.triggers || ''
  if (!trigger || /^intake_condition/i.test(trigger)) return true

  // Extract component IDs from the trigger string (e.g. "DECK-01 present")
  const cids = trigger.match(/[A-Z]+-\d+/g) || []
  if (cids.length) {
    return cids.some(cid => presentSet.has(cid) || sellerConfirmedPresent.has(cid))
  }

  return true
}

// ── component ─────────────────────────────────────────────────────────────────

export default function QuestionnaireStep({ sessionId, photoData, onDone }) {
  const [qBank, setQBank]           = useState(null)
  const [answers, setAnswers]       = useState({})
  const [loading, setLoading]       = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError]           = useState(null)

  const {
    photoTagsForCapture    = [],
    sellerConfirmedTags    = [],
    absencePresenceAnswers = [],
  } = photoData

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

      const presentSet = buildPresentSet(photoTagsForCapture, absencePresenceAnswers)
      const sellerConfirmedPresent = new Set(
        sellerConfirmedTags.filter(t => t.present === true).map(t => t.component_id)
      )

      // Presence answers
      const presenceAnswers = []
      for (const q of qBank.presence_questions) {
        const val = answers[`P_${q.question_id}`]
        if (val) {
          const cids = Array.isArray(q.maps_to) ? q.maps_to : [q.maps_to].filter(Boolean)
          for (const cid of cids) {
            presenceAnswers.push({ question_id: q.question_id, component_id: cid, answer: val })
          }
        }
      }

      // Condition answers — only from currently visible questions (prune ghost answers)
      const conditionQs = qBank.condition_questions.filter(q => q.question_id !== 'Q-INSP')
      const visibleCQIds = new Set(
        conditionQs.filter(q =>
          ALWAYS_ASK.has(q.question_id) ||
          isVisible(q, conditionQs, presentSet, answers, sellerConfirmedPresent, 'C')
        ).map(q => q.question_id)
      )

      const conditionAnswers = []
      for (const q of conditionQs) {
        if (!visibleCQIds.has(q.question_id)) continue
        const val = answers[`C_${q.question_id}`]
        if (val) {
          const cids = Array.isArray(q.maps_to) ? q.maps_to : [q.maps_to].filter(Boolean)
          for (const cid of cids) {
            conditionAnswers.push({ question_id: q.question_id, component_id: cid, answer: val })
          }
        }
      }

      // Constraints — only visible ones
      const visibleConstraints = qBank.constraints_intake.filter(q =>
        isVisible(q, qBank.constraints_intake, presentSet, answers, sellerConfirmedPresent, 'CI')
      )
      const sellerInputs = {}
      for (const q of visibleConstraints) {
        const val = answers[`CI_${q.question_id}`]
        if (!val) continue
        if (q.question_id === 'C-PAYOFF')   sellerInputs.mortgage_payoff  = parseFloat(val) || 0
        if (q.question_id === 'C-TIMELINE') sellerInputs.timeline         = val
        if (q.question_id === 'C-FUND-1')   sellerInputs.can_fund_upfront = val === 'yes'
        if (q.question_id === 'C-FUND-2')   sellerInputs.can_fund_financed = val === 'yes'
      }

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

  if (loading) return <p>Loading questions…</p>
  if (!qBank)  return <p style={{ color: 'red' }}>Failed to load questionnaire. {error}</p>

  const tagMap     = buildTagMap(photoTagsForCapture)
  const presentSet = buildPresentSet(photoTagsForCapture, absencePresenceAnswers)
  const sellerConfirmedPresent = new Set(
    sellerConfirmedTags.filter(t => t.present === true).map(t => t.component_id)
  )

  function visionHint(cid) {
    const t = tagMap[cid]
    if (!t || t.confidence < 0.5) return null
    return `Vision: ${t.tag || t.condition} (${(t.confidence * 100).toFixed(0)}% conf)`
  }

  // Condition questions: exclude Q-INSP (handled at intake), apply branching
  const conditionQs = qBank.condition_questions.filter(q => q.question_id !== 'Q-INSP')
  const visibleConditionQs = conditionQs.filter(q =>
    ALWAYS_ASK.has(q.question_id) ||
    isVisible(q, conditionQs, presentSet, answers, sellerConfirmedPresent, 'C')
  )

  // Constraints: apply branching (C-FUND-2 gated on C-FUND-1=no)
  const visibleConstraints = qBank.constraints_intake.filter(q =>
    isVisible(q, qBank.constraints_intake, presentSet, answers, sellerConfirmedPresent, 'CI')
  )

  return (
    <form onSubmit={submit}>
      <h2 style={{ fontSize: 16, marginBottom: 8 }}>Questionnaire</h2>
      <p style={{ fontSize: 13, color: '#555', marginBottom: 20 }}>
        Questions narrow based on your answers. Vision's draft is shown as a hint only — your answers override it.
      </p>

      {/* Presence */}
      <section style={sectionStyle}>
        <h3 style={h3}>What does your home have?</h3>
        {qBank.presence_questions.map(q => {
          const cid  = Array.isArray(q.maps_to) ? q.maps_to[0] : q.maps_to
          const hint = cid ? visionHint(cid) : null
          return (
            <QuestionRow key={q.question_id} q={q} prefix="P"
              answers={answers} onAnswer={answer} hint={hint} />
          )
        })}
      </section>

      {/* Condition — branching */}
      {visibleConditionQs.length > 0 && (
        <section style={sectionStyle}>
          <h3 style={h3}>Condition — what you know or can check</h3>
          {visibleConditionQs.map(q => {
            const cid  = Array.isArray(q.maps_to) ? q.maps_to[0] : q.maps_to
            const hint = cid ? visionHint(cid) : null
            return (
              <QuestionRow key={q.question_id} q={q} prefix="C"
                answers={answers} onAnswer={answer} hint={hint} />
            )
          })}
        </section>
      )}

      {/* Constraints — branching */}
      <section style={sectionStyle}>
        <h3 style={h3}>Your situation</h3>
        {visibleConstraints.map(q => (
          <QuestionRow key={q.question_id} q={q} prefix="CI"
            answers={answers} onAnswer={answer} />
        ))}
      </section>

      {error && <p style={{ color: 'red', marginBottom: 8 }}>{error}</p>}
      <button style={btnStyle} type="submit" disabled={submitting}>
        {submitting ? 'Submitting…' : 'Submit and see report'}
      </button>
    </form>
  )
}

function QuestionRow({ q, prefix, answers, onAnswer, hint }) {
  const key = `${prefix}_${q.question_id}`
  const val = answers[key] ?? ''

  return (
    <div style={{ marginBottom: 16 }}>
      <label style={{ fontSize: 13, fontWeight: 500, display: 'block', marginBottom: 3 }}>
        {q.prompt}
      </label>
      {hint && (
        <div style={{ fontSize: 11, color: '#888', marginBottom: 4, fontStyle: 'italic' }}>
          {hint}
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
          {(q.options || []).map(o => <option key={o} value={o}>{o.replace(/_/g, ' ')}</option>)}
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
const sectionStyle = { marginBottom: 24, paddingBottom: 16, borderBottom: '1px solid #eee' }
const h3          = { fontSize: 14, marginTop: 0, marginBottom: 14 }
const selectStyle = { fontSize: 13, padding: '4px 6px' }
