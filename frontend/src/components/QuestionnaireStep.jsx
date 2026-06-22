import React, { useState, useEffect, useMemo } from 'react'
import { getQuestions, submitCapture } from '../api'

// ── presence helpers ──────────────────────────────────────────────────────────

function buildPhotoPresent(photoTagsForCapture) {
  const s = new Set()
  for (const t of photoTagsForCapture) {
    if ((t.confidence ?? 1) >= 0.5) s.add(t.component_id)
  }
  return s
}

function buildSellerConfirmedPresent(sellerConfirmedTags) {
  return new Set(
    sellerConfirmedTags.filter(t => t.present === true).map(t => t.component_id)
  )
}

function buildTagMap(photoTagsForCapture) {
  const map = {}
  for (const tag of photoTagsForCapture) {
    if (!map[tag.component_id] || (tag.confidence ?? 0) > (map[tag.component_id].confidence ?? 0)) {
      map[tag.component_id] = tag
    }
  }
  return map
}

// Build map: cid → first presence question that maps to it
function buildPresenceQMap(presenceQs) {
  const m = {}
  for (const q of presenceQs) {
    const cids = Array.isArray(q.maps_to) ? q.maps_to : [q.maps_to].filter(Boolean)
    for (const cid of cids) {
      if (!m[cid]) m[cid] = q
    }
  }
  return m
}

// Is a component confirmed present?
// - Seller-confirmed from photo review OR confident photo tag → true
// - Explicit presence question → 'yes' (yes_no) or non-'no' (single_select)
// - No presence question → true (always-present component)
function isPresent(cid, presenceQMap, answers, photoPresentSet, confirmedPresentSet) {
  if (confirmedPresentSet.has(cid) || photoPresentSet.has(cid)) return true
  const pq = presenceQMap[cid]
  if (!pq) return true  // no gate → always visible
  const val = answers[`P_${pq.id}`]
  if (!val) return false  // not yet answered → suppress children
  if (pq.type === 'yes_no') return val === 'yes'
  return val !== 'no'
}

// Parse "CID present OR CID2 present" trigger into a visibility decision
function evalTrigger(trigger, presenceQMap, answers, photoPresentSet, confirmedPresentSet) {
  if (!trigger || trigger === 'always_ask') return true
  // Constraint parent-gate: "C-PAYUP = no"
  if (/^[\w-]+\s*=\s*.+$/.test(trigger)) {
    const [parentId, reqVal] = trigger.split(/\s*=\s*/)
    return answers[`C_${parentId.trim()}`] === reqVal.trim()
  }
  // "CID present OR CID2 present"
  const parts = trigger.split(/\s+OR\s+/)
  return parts.some(part => {
    const cid = part.replace(/\s+present$/i, '').trim()
    if (!/^[A-Z]+-\d+$/.test(cid)) return true  // unknown format → show
    return isPresent(cid, presenceQMap, answers, photoPresentSet, confirmedPresentSet)
  })
}

// ── main component ────────────────────────────────────────────────────────────

export default function QuestionnaireStep({ sessionId, photoData, onDone }) {
  const [qBank,      setQBank]      = useState(null)
  const [answers,    setAnswers]    = useState({})
  const [loading,    setLoading]    = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error,      setError]      = useState(null)

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

  const photoPresentSet     = useMemo(() => buildPhotoPresent(photoTagsForCapture), [photoTagsForCapture])
  const confirmedPresentSet = useMemo(() => buildSellerConfirmedPresent(sellerConfirmedTags), [sellerConfirmedTags])
  const tagMap              = useMemo(() => buildTagMap(photoTagsForCapture), [photoTagsForCapture])

  const presenceQMap = useMemo(
    () => qBank ? buildPresenceQMap(qBank.presence_questions || []) : {},
    [qBank]
  )

  function answer(key, value) {
    setAnswers(prev => ({ ...prev, [key]: value }))
  }

  function isVis(trigger) {
    return evalTrigger(trigger, presenceQMap, answers, photoPresentSet, confirmedPresentSet)
  }

  function visionHint(cid) {
    const t = tagMap[cid]
    if (!t || (t.confidence ?? 0) < 0.5) return null
    return `Vision: ${t.tag || t.condition || 'detected'} (${Math.round((t.confidence ?? 1) * 100)}% conf)`
  }

  // ── submit ──────────────────────────────────────────────────────────────────

  async function submit(e) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      if (!qBank) throw new Error('Questions not loaded.')

      // 1. Presence answers
      const presenceAnswers = []
      for (const q of qBank.presence_questions || []) {
        const val = answers[`P_${q.id}`]
        if (!val) continue
        const cids = Array.isArray(q.maps_to) ? q.maps_to : [q.maps_to].filter(Boolean)
        for (const cid of cids) {
          presenceAnswers.push({ question_id: q.id, component_id: cid, answer: val })
        }
      }

      // 2. Condition answers (visible only)
      const conditionAnswers = []
      for (const q of qBank.condition_questions || []) {
        if (!isVis(q.triggers)) continue
        const val = answers[`Q_${q.id}`]
        if (!val) continue
        const cids = Array.isArray(q.maps_to) ? q.maps_to : [q.maps_to].filter(Boolean)
        for (const cid of cids) {
          conditionAnswers.push({ question_id: q.id, component_id: cid, answer: val })
        }
      }

      // 3. Disclosure answers → treated as condition signals
      for (const q of qBank.disclosure_questions || []) {
        const val = answers[`D_${q.id}`]
        if (!val || val === 'no') continue
        const cids = q.maps_to === '_closing_hoa'
          ? []
          : (Array.isArray(q.maps_to) ? q.maps_to : [q.maps_to].filter(Boolean))
        const desc = answers[`D_${q.id}_desc`] || ''
        for (const cid of cids) {
          conditionAnswers.push({ question_id: q.id, component_id: cid, answer: val, description: desc })
        }
      }

      // 4. Cosmetic upgrade answers → treated as condition signals with upgrade type
      for (const q of qBank.cosmetic_upgrade_questions || []) {
        if (!isVis(q.triggers)) continue
        const val = answers[`U_${q.id}`]
        if (!val) continue
        const cids = Array.isArray(q.maps_to) ? q.maps_to : [q.maps_to].filter(Boolean)
        for (const cid of cids) {
          conditionAnswers.push({ question_id: q.id, component_id: cid, answer: val, work_type: 'upgrade' })
        }
      }

      // 5. Constraints → seller_inputs
      const sellerInputs = {}
      for (const q of qBank.constraints_questions || []) {
        if (!isVis(q.triggers)) continue
        const val = answers[`C_${q.id}`]
        if (val == null || val === '') continue
        const key = q.maps_to
        if (!key || key === '_closing_hoa') continue
        if (q.type === 'currency') {
          sellerInputs[key] = parseFloat(val) || 0
        } else if (q.type === 'yes_no') {
          sellerInputs[key] = val === 'yes'
        } else {
          sellerInputs[key] = val
        }
      }
      // Sum payoff components
      sellerInputs.mortgage_payoff = (sellerInputs.payoff_primary || 0)
                                   + (sellerInputs.payoff_secondary || 0)
                                   + (sellerInputs.payoff_liens || 0)

      // HOA from disclosure D-HOA
      const hoaAns = answers['D_D-HOA']
      if (hoaAns === 'yes') sellerInputs._closing_hoa = true

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

  // ── render ──────────────────────────────────────────────────────────────────

  if (loading) return <p>Loading questions…</p>
  if (!qBank)  return <p style={{ color: 'red' }}>Failed to load questionnaire. {error}</p>

  const visibleConditionQs = (qBank.condition_questions || []).filter(q => isVis(q.triggers))
  const visibleUpgradeQs   = (qBank.cosmetic_upgrade_questions || []).filter(q => isVis(q.triggers))
  const visibleConstraints = (qBank.constraints_questions || []).filter(q => isVis(q.triggers))

  return (
    <form onSubmit={submit}>
      <h2 style={{ fontSize: 16, marginBottom: 8 }}>Questionnaire</h2>
      <p style={{ fontSize: 13, color: '#555', marginBottom: 20 }}>
        Questions narrow as you answer. Your answers override any vision draft shown as a hint.
      </p>

      {/* ── Step 1: About your home ── */}
      <section style={sectionStyle}>
        <h3 style={h3}>About your home</h3>
        <p style={sectionNote}>
          Answer to reveal follow-up questions. If you don't have something, it won't appear.
        </p>
        {(qBank.presence_questions || []).map(q => {
          const cid  = Array.isArray(q.maps_to) ? q.maps_to[0] : q.maps_to
          return (
            <QuestionRow key={q.id} q={q} prefix="P"
              answers={answers} onAnswer={answer}
              hint={cid ? visionHint(cid) : null} />
          )
        })}
      </section>

      {/* ── Step 1b: Condition ── */}
      {visibleConditionQs.length > 0 && (
        <section style={sectionStyle}>
          <h3 style={h3}>Condition — what you know or can check</h3>
          <p style={sectionNote}>
            "Unsure / can't access" means we'll flag it as something to get looked at — no cost guessed.
          </p>
          {visibleConditionQs.map(q => {
            const cid = Array.isArray(q.maps_to) ? q.maps_to[0] : q.maps_to
            return (
              <QuestionRow key={q.id} q={q} prefix="Q"
                answers={answers} onAnswer={answer}
                hint={cid ? visionHint(cid) : null} />
            )
          })}
        </section>
      )}

      {/* ── Optional upgrades ── */}
      {visibleUpgradeQs.length > 0 && (
        <section style={sectionStyle}>
          <h3 style={h3}>Optional — quick wins that often pay for themselves</h3>
          <p style={sectionNote}>
            These are cosmetic refreshes, not defects. Small spend, often strong return at sale.
          </p>
          {visibleUpgradeQs.map(q => {
            const cid = Array.isArray(q.maps_to) ? q.maps_to[0] : q.maps_to
            return (
              <QuestionRow key={q.id} q={q} prefix="U"
                answers={answers} onAnswer={answer}
                hint={cid ? visionHint(cid) : null} />
            )
          })}
        </section>
      )}

      {/* ── Step 2: Disclosures ── */}
      {(qBank.disclosure_questions || []).length > 0 && (
        <section style={sectionStyle}>
          <h3 style={h3}>Anything you already know about</h3>
          <p style={sectionNote}>
            SC requires disclosure of known material defects. "Yes" opens a description field.
          </p>
          {(qBank.disclosure_questions || []).map(q => (
            <DisclosureRow key={q.id} q={q} answers={answers} onAnswer={answer} />
          ))}
        </section>
      )}

      {/* ── Step 3: Constraints ── */}
      {visibleConstraints.length > 0 && (
        <section style={sectionStyle}>
          <h3 style={h3}>Your situation</h3>
          <p style={sectionNote}>
            Helps show what you'd actually walk away with. Stays private.
          </p>
          <PayoffBlock answers={answers} onAnswer={answer} />
          {visibleConstraints.filter(q =>
            !['C-PAYOFF-PRIMARY', 'C-PAYOFF-SECOND', 'C-PAYOFF-LIENS'].includes(q.id)
          ).map(q => (
            <QuestionRow key={q.id} q={q} prefix="C" answers={answers} onAnswer={answer} />
          ))}
        </section>
      )}

      {error && <p style={{ color: 'red', marginBottom: 8 }}>{error}</p>}
      <button style={btnStyle} type="submit" disabled={submitting}>
        {submitting ? 'Submitting…' : 'Submit and see report'}
      </button>
    </form>
  )
}

// ── PayoffBlock: three-line payoff split ──────────────────────────────────────
function PayoffBlock({ answers, onAnswer }) {
  const primary   = parseFloat(answers['C_C-PAYOFF-PRIMARY'] || '0') || 0
  const secondary = parseFloat(answers['C_C-PAYOFF-SECOND']  || '0') || 0
  const liens     = parseFloat(answers['C_C-PAYOFF-LIENS']   || '0') || 0
  const total     = primary + secondary + liens

  return (
    <div style={{ marginBottom: 20 }}>
      <label style={{ fontSize: 13, fontWeight: 500, display: 'block', marginBottom: 4 }}>
        What's owed against your home?
      </label>
      <p style={{ fontSize: 12, color: '#666', margin: '0 0 10px', lineHeight: 1.5 }}>
        Include all balances. Forgetting a HELOC, second mortgage, or lien is the most
        common reason net proceeds come out wrong.
      </p>
      {[
        { label: 'Primary mortgage balance',       key: 'C_C-PAYOFF-PRIMARY' },
        { label: 'Second mortgage or HELOC',       key: 'C_C-PAYOFF-SECOND'  },
        { label: 'Liens, unpaid taxes, or other', key: 'C_C-PAYOFF-LIENS'   },
      ].map(({ label, key }) => (
        <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
          <span style={{ fontSize: 13, width: 230 }}>{label}</span>
          <input type="number" min={0} step={1000} placeholder="$0"
            value={answers[key] || ''}
            onChange={e => onAnswer(key, e.target.value)}
            style={{ fontSize: 13, padding: '4px 6px', width: 130 }} />
        </div>
      ))}
      {total > 0 && (
        <div style={{ fontSize: 13, fontWeight: 600, color: '#333', marginTop: 4 }}>
          Total payoff: ${total.toLocaleString('en-US', { maximumFractionDigits: 0 })}
        </div>
      )}
    </div>
  )
}

// ── DisclosureRow: yes/no + optional text description ─────────────────────────
function DisclosureRow({ q, answers, onAnswer }) {
  const key  = `D_${q.id}`
  const desc = `D_${q.id}_desc`
  const val  = answers[key] ?? ''

  return (
    <div style={{ marginBottom: 16 }}>
      <label style={{ fontSize: 13, fontWeight: 500, display: 'block', marginBottom: 4 }}>
        {q.prompt}
      </label>
      <div>
        {['yes', 'no'].map(opt => (
          <label key={opt} style={{ marginRight: 16, fontSize: 13 }}>
            <input type="radio" name={key} value={opt}
              checked={val === opt} onChange={() => onAnswer(key, opt)} />
            {' '}{opt}
          </label>
        ))}
      </div>
      {val === 'yes' && (
        <textarea
          placeholder="Brief description (optional but helpful)"
          value={answers[desc] || ''}
          onChange={e => onAnswer(desc, e.target.value)}
          style={{ marginTop: 6, fontSize: 12, width: '100%', maxWidth: 440,
                   padding: '6px 8px', minHeight: 60, boxSizing: 'border-box' }}
        />
      )}
    </div>
  )
}

// ── QuestionRow: single_select / yes_no / currency ───────────────────────────
function QuestionRow({ q, prefix, answers, onAnswer, hint }) {
  const key = `${prefix}_${q.id}`
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

      {(q.type === 'yes_no') && (
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

      {(q.type === 'single_select') && (
        <select style={selectStyle} value={val} onChange={e => onAnswer(key, e.target.value)}>
          <option value="">— select —</option>
          {(q.options || []).map(o => (
            <option key={o} value={o}>{o}</option>
          ))}
        </select>
      )}

      {(q.type === 'currency') && (
        <input type="number" min={0} step={100} placeholder="$0"
          style={{ fontSize: 13, padding: '4px 6px', width: 160 }}
          value={val} onChange={e => onAnswer(key, e.target.value)} />
      )}
    </div>
  )
}

// ── styles ────────────────────────────────────────────────────────────────────
const sectionStyle = { marginBottom: 24, paddingBottom: 16, borderBottom: '1px solid #eee' }
const h3           = { fontSize: 14, marginTop: 0, marginBottom: 6 }
const sectionNote  = { fontSize: 12, color: '#666', marginTop: 0, marginBottom: 14 }
const selectStyle  = { fontSize: 13, padding: '4px 6px' }
const btnStyle     = { padding: '8px 20px', fontSize: 14, cursor: 'pointer' }
