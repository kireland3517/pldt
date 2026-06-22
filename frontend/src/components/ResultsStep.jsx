import React, { useState, useEffect, useCallback } from 'react'
import { getCompute, updateInputs } from '../api'

const PLAN_LABELS = {
  leaner:        'Leaner — floor only',
  recommended:   'Recommended',
  do_everything: 'Do everything',
}

const PLAN_DESCRIPTIONS = {
  leaner:        'Mandatory work only. Smallest upfront cost.',
  recommended:   'Floor + improvements that pay back ≥ 75% at sale.',
  do_everything: 'Every actionable item in the repair table.',
}

const PATH_LABELS = {
  repair:  'Repair',
  replace: 'Replace',
  credit:  'Buyer credit',
  leave:   'Leave as-is',
}

function fmt(n) {
  if (n == null || isNaN(n)) return '—'
  return '$' + Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 })
}

function fmtRange(lo, hi) {
  if (lo == null && hi == null) return '—'
  if (lo == null) return `up to ${fmt(hi)}`
  if (hi == null) return `${fmt(lo)}+`
  return `${fmt(lo)} – ${fmt(hi)}`
}

// ── Repair plan helpers ──────────────────────────────────────────────────────

function buildRepairPlan(repairTable, floorResult, plans, level) {
  if (!repairTable?.length) return { floorItems: [], discretionary: [], notIncluded: [] }

  const floorIds    = new Set((floorResult?.items || []).map(i => i.component_id))
  const includedIds = new Set((plans?.[level]?.included_items || []))
  const floorMeta   = Object.fromEntries((floorResult?.items || []).map(i => [i.component_id, i]))

  const floorItems    = []
  const discretionary = []
  const notIncluded   = []

  for (const row of repairTable) {
    const cid      = row.component_id
    const inFloor  = floorIds.has(cid)
    const included = includedIds.has(cid)

    if (inFloor) {
      floorItems.push({ ...row, floor_reason: floorMeta[cid]?.reason || 'required' })
    } else if (included) {
      discretionary.push(row)
    } else if (row.better_value !== 'leave' && row.condition_detected) {
      notIncluded.push(row)
    }
  }

  return { floorItems, discretionary, notIncluded }
}

// ── Component ────────────────────────────────────────────────────────────────

export default function ResultsStep({ sessionId }) {
  const [result,       setResult]       = useState(null)
  const [loading,      setLoading]      = useState(true)
  const [error,        setError]        = useState(null)
  const [commission,   setCommission]   = useState(6)
  const [payoffPrimary,   setPayoffPrimary]   = useState(0)
  const [payoffSecondary, setPayoffSecondary] = useState(0)
  const [payoffOther,     setPayoffOther]     = useState(0)
  const [knobDirty,    setKnobDirty]    = useState(false)
  const [applying,     setApplying]     = useState(false)
  const [selectedPlan, setSelectedPlan] = useState('recommended')

  const payoffTotal = payoffPrimary + payoffSecondary + payoffOther

  const load = useCallback(async (refresh = false) => {
    setLoading(true)
    setError(null)
    try {
      const r = await getCompute(sessionId, refresh)
      setResult(r)
      if (!refresh) {
        if (r.commission_rate) setCommission(Math.round(r.commission_rate * 100 * 10) / 10)
        const si = r.seller_inputs || {}
        // Restore breakdown if stored; fall back to total in primary
        if (si.payoff_primary != null) {
          setPayoffPrimary(si.payoff_primary)
          setPayoffSecondary(si.payoff_secondary || 0)
          setPayoffOther(si.payoff_other || 0)
        } else if (si.mortgage_payoff > 0) {
          setPayoffPrimary(si.mortgage_payoff)
        }
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [sessionId])

  useEffect(() => { load() }, [load])

  async function applyKnobs() {
    setApplying(true)
    try {
      await updateInputs(sessionId, {
        commission_rate: commission / 100,
        seller_inputs: {
          mortgage_payoff:  payoffTotal,
          payoff_primary:   payoffPrimary,
          payoff_secondary: payoffSecondary,
          payoff_other:     payoffOther,
        },
      })
      await load(true)
      setKnobDirty(false)
    } catch (err) {
      setError(err.message)
    } finally {
      setApplying(false)
    }
  }

  if (loading) return <p style={{ padding: 24 }}>Computing results…</p>
  if (error)   return <p style={{ color: 'red', padding: 24 }}>Error: {error}</p>
  if (!result) return null

  const val      = result.valuation || result.as_is_range || {}
  const plans    = result.plans     || {}
  const floor    = result.floor     || {}
  const repair   = result.repair_table || []
  const planKeys = ['leaner', 'recommended', 'do_everything'].filter(k => plans[k])

  // Underwater: every plan nets below zero
  const isUnderwater = planKeys.length > 0 &&
    planKeys.every(k => (plans[k]?.net_proceeds?.net_proceeds ?? 0) < 0)

  const { floorItems, discretionary, notIncluded } =
    buildRepairPlan(repair, floor, plans, selectedPlan)

  const selPlan = plans[selectedPlan] || {}
  const selNet  = selPlan.net_proceeds || {}

  return (
    <div>
      <h2 style={{ fontSize: 16, marginBottom: 4 }}>Report</h2>

      {/* ── Valuation ── */}
      <section style={sectionStyle}>
        <h3 style={h3}>As-is value estimate</h3>
        <div style={gridStyle}>
          <Stat label="Low"        value={fmt(val.low)} />
          <Stat label="Mid"        value={fmt(val.mid)} highlight />
          <Stat label="High"       value={fmt(val.high)} />
          {val.avm_avg  && <Stat label="AVM avg"    value={fmt(val.avm_avg)} />}
          {val.confidence && <Stat label="Confidence" value={`${(val.confidence * 100).toFixed(0)}%`} />}
        </div>
        {val.note && <p style={noteStyle}>{val.note}</p>}

        {val.comp_detail?.length > 0 && (
          <details style={{ marginTop: 12 }}>
            <summary style={detailsLink}>Comparable sales detail</summary>
            <table style={tableStyle}>
              <thead><tr>
                <th style={th}>Address</th><th style={th}>Price</th>
                <th style={th}>$/sqft</th><th style={th}>Weight</th><th style={th}>Note</th>
              </tr></thead>
              <tbody>
                {val.comp_detail.map((c, i) => (
                  <tr key={i}>
                    <td style={td}>{c.address}</td>
                    <td style={td}>{fmt(c.price)}</td>
                    <td style={td}>${c.actual_ppsf?.toFixed(2)}</td>
                    <td style={td}>{(c.weight * 100).toFixed(1)}%</td>
                    <td style={td}>{c.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        )}
      </section>

      {/* ── Underwater state ── */}
      {isUnderwater && (
        <section style={{ ...sectionStyle, borderColor: '#f0c040', background: '#fffbe6' }}>
          <h3 style={{ ...h3, color: '#7a5c00' }}>Your current numbers show a shortfall</h3>
          <p style={{ fontSize: 13, lineHeight: 1.6, marginTop: 0 }}>
            Based on your home's estimated value, the mandatory repairs, closing costs, and
            mortgage payoff, every plan we modeled results in out-of-pocket costs at closing.
          </p>
          <p style={{ fontSize: 13, lineHeight: 1.6 }}>
            The most common causes: the payoff balance entered is higher than the home can
            support at current values, or mandatory work costs exceed the equity available.
          </p>
          <p style={{ fontSize: 13, lineHeight: 1.6 }}>
            This doesn't mean you can't sell — it means the numbers as entered don't leave a
            profit margin. Before deciding anything, confirm your exact payoff with your lender
            and review the required work list below to check whether any items were flagged
            in error.
          </p>
          <p style={{ fontSize: 12, color: '#888' }}>
            Adjust the payoff amount in the "Adjust" section below if the figure isn't accurate.
          </p>
        </section>
      )}

      {/* ── Plan comparison cards ── */}
      <section style={sectionStyle}>
        <h3 style={h3}>Plans — estimated net proceeds</h3>
        <p style={noteStyle}>
          Net proceeds = sale price − mandatory work − plan repairs − closing costs − payoff.
        </p>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 8 }}>
          {planKeys.map(key => {
            const p   = plans[key]
            const net = p.net_proceeds || {}
            const isNeg = (net.net_proceeds ?? 0) < 0
            return (
              <div key={key}
                style={planCardStyle(key, selectedPlan === key)}
                onClick={() => setSelectedPlan(key)}
              >
                <div style={{ fontWeight: 700, marginBottom: 4, fontSize: 13 }}>
                  {PLAN_LABELS[key]}
                </div>
                <div style={{ fontSize: 11, color: '#666', marginBottom: 8 }}>
                  {PLAN_DESCRIPTIONS[key]}
                </div>
                <div style={{ fontSize: 15, fontWeight: 700, color: isNeg ? '#c00' : '#1a7f37' }}>
                  {fmt(net.net_proceeds)}
                </div>
                <div style={{ fontSize: 11, color: '#777', marginTop: 4 }}>
                  {p.dom?.estimated_dom} days est. · {p.item_count} items
                </div>
                {net.line_items && (
                  <details style={{ marginTop: 8 }} onClick={e => e.stopPropagation()}>
                    <summary style={detailsLink}>Closing cost breakdown</summary>
                    {net.line_items.map((li, i) => (
                      <div key={i} style={{ fontSize: 11, display: 'flex', justifyContent: 'space-between', marginTop: 2 }}>
                        <span>{li.label}</span><span>{fmt(li.amount)}</span>
                      </div>
                    ))}
                  </details>
                )}
              </div>
            )
          })}
        </div>
        <p style={{ fontSize: 11, color: '#999', marginTop: 8 }}>
          Estimated days-on-market is based on historical averages and seasonality.
          A competitive seller's market or slow buyer's market will shift this timeline.
        </p>
        <p style={{ fontSize: 11, color: '#999' }}>
          Time-to-sell covers listing to closing only. It does not include time to complete
          major construction — your actual carrying costs will be higher while work is underway.
        </p>
      </section>

      {/* ── Repair plan detail (for selected plan) ── */}
      <section style={sectionStyle}>
        <h3 style={h3}>Repair plan — {PLAN_LABELS[selectedPlan]}</h3>
        <div style={{ marginBottom: 12 }}>
          {planKeys.map(key => (
            <button key={key}
              style={tabStyle(key === selectedPlan)}
              onClick={() => setSelectedPlan(key)}>
              {PLAN_LABELS[key]}
            </button>
          ))}
        </div>

        {/* Floor items */}
        {floorItems.length > 0 && (
          <div style={{ marginBottom: 20 }}>
            <div style={subheadStyle}>
              Required work — {floorItems.length} item{floorItems.length !== 1 ? 's' : ''}
            </div>
            <p style={{ ...noteStyle, marginBottom: 8 }}>
              These must be addressed before listing. Lenders flag them, or they are
              safety issues buyers' agents will call out.
            </p>
            <table style={tableStyle}>
              <thead>
                <tr>
                  <th style={th}>Component</th>
                  <th style={th}>Why required</th>
                  <th style={th}>Action</th>
                  <th style={th}>Repair range</th>
                  <th style={th}>Replace range</th>
                  <th style={th}>Rec. path</th>
                  <th style={th}>Note</th>
                </tr>
              </thead>
              <tbody>
                {floorItems.map((item, i) => (
                  <tr key={i} style={{ background: i % 2 === 0 ? '#fff8f0' : '#fff' }}>
                    <td style={{ ...td, fontWeight: 500 }}>{item.display_name}</td>
                    <td style={{ ...td, color: '#b45309', fontSize: 11 }}>{item.floor_reason}</td>
                    <td style={td}>{PATH_LABELS[item.better_value] || item.better_value}</td>
                    <td style={td}>{fmtRange(item.repair_low, item.repair_high)}</td>
                    <td style={td}>{fmtRange(item.replace_low, item.replace_high)}</td>
                    <td style={{ ...td, fontWeight: 600 }}>{PATH_LABELS[item.better_value] || '—'}</td>
                    <td style={{ ...td, fontSize: 11, color: '#777' }}>{item.notes || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ fontSize: 12, color: '#555', marginTop: 6 }}>
              Required work total: <strong>{fmtRange(floor.cost_low, floor.cost_high)}</strong>
              {floor.cost_mid ? ` (mid ${fmt(floor.cost_mid)})` : ''}
            </div>
          </div>
        )}

        {/* Discretionary items */}
        {discretionary.length > 0 && (
          <div style={{ marginBottom: 20 }}>
            <div style={subheadStyle}>
              Additional work in this plan — {discretionary.length} item{discretionary.length !== 1 ? 's' : ''}
            </div>
            <p style={{ ...noteStyle, marginBottom: 8 }}>
              Not required, but included because the value return justifies the spend.
            </p>
            <table style={tableStyle}>
              <thead>
                <tr>
                  <th style={th}>Component</th>
                  <th style={th}>Condition</th>
                  <th style={th}>Action</th>
                  <th style={th}>Repair range</th>
                  <th style={th}>Replace range</th>
                  <th style={th}>Value return</th>
                  <th style={th}>Note</th>
                </tr>
              </thead>
              <tbody>
                {discretionary.map((item, i) => (
                  <tr key={i} style={{ background: i % 2 === 0 ? '#f0f9f0' : '#fff' }}>
                    <td style={{ ...td, fontWeight: 500 }}>{item.display_name}</td>
                    <td style={{ ...td, fontSize: 11, color: '#555' }}>{item.condition_detected || '—'}</td>
                    <td style={td}>{PATH_LABELS[item.better_value] || item.better_value}</td>
                    <td style={td}>{fmtRange(item.repair_low, item.repair_high)}</td>
                    <td style={td}>{fmtRange(item.replace_low, item.replace_high)}</td>
                    <td style={{ ...td, fontSize: 11 }}>{item.effective_recoup_label || `${item.recoup_pct?.toFixed(0)}%`}</td>
                    <td style={{ ...td, fontSize: 11, color: '#777' }}>{item.notes || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Not included */}
        {notIncluded.length > 0 && (
          <details>
            <summary style={detailsLink}>
              {notIncluded.length} item{notIncluded.length !== 1 ? 's' : ''} not included in this plan
            </summary>
            <table style={{ ...tableStyle, marginTop: 8 }}>
              <thead>
                <tr>
                  <th style={th}>Component</th>
                  <th style={th}>Condition</th>
                  <th style={th}>Why skipped</th>
                  <th style={th}>Value return</th>
                </tr>
              </thead>
              <tbody>
                {notIncluded.map((item, i) => (
                  <tr key={i}>
                    <td style={td}>{item.display_name}</td>
                    <td style={{ ...td, fontSize: 11 }}>{item.condition_detected || '—'}</td>
                    <td style={{ ...td, fontSize: 11, color: '#888' }}>
                      {item.better_value === 'leave'
                        ? 'Leave as-is recommended'
                        : `Not in ${PLAN_LABELS[selectedPlan].toLowerCase()} scope`}
                    </td>
                    <td style={{ ...td, fontSize: 11 }}>
                      {item.effective_recoup_label || `${item.recoup_pct?.toFixed(0)}%`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        )}

        {floorItems.length === 0 && discretionary.length === 0 && (
          <p style={{ fontSize: 13, color: '#888' }}>
            No repair items found. Make sure photos have been tagged and the questionnaire submitted.
          </p>
        )}
      </section>

      {/* ── Adjust knobs ── */}
      <section style={sectionStyle}>
        <h3 style={h3}>Adjust inputs</h3>

        <label style={labelStyle}>
          Commission rate: <strong>{commission}%</strong>
          <input type="range" min={1} max={8} step={0.5}
            value={commission}
            onChange={e => { setCommission(+e.target.value); setKnobDirty(true) }}
            style={{ marginLeft: 8, verticalAlign: 'middle' }}
          />
        </label>

        <div style={{ marginTop: 14 }}>
          <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 6 }}>
            Mortgage payoff — total: <strong>{fmt(payoffTotal)}</strong>
          </div>
          <p style={{ fontSize: 12, color: '#666', margin: '0 0 8px' }}>
            Include all balances so the net estimate is accurate.
            Forgetting a HELOC or lien is the most common source of a wrong net number.
          </p>
          {[
            { label: 'Primary mortgage',            val: payoffPrimary,   set: setPayoffPrimary },
            { label: 'Second mortgage / HELOC',     val: payoffSecondary, set: setPayoffSecondary },
            { label: 'Liens, unpaid taxes, or other', val: payoffOther,   set: setPayoffOther },
          ].map(({ label, val: v, set }) => (
            <label key={label} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, fontSize: 13 }}>
              <span style={{ width: 220 }}>{label}</span>
              <input type="number" min={0} step={1000} value={v}
                onChange={e => { set(+e.target.value); setKnobDirty(true) }}
                style={{ width: 120, padding: '3px 6px', fontSize: 13 }} />
            </label>
          ))}
        </div>

        {knobDirty && (
          <button style={{ ...btnStyle, marginTop: 10 }} onClick={applyKnobs} disabled={applying}>
            {applying ? 'Recomputing…' : 'Apply and recompute'}
          </button>
        )}
        {error && <p style={{ color: 'red', fontSize: 13, marginTop: 8 }}>{error}</p>}
      </section>
    </div>
  )
}

function Stat({ label, value, highlight }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 11, color: '#888' }}>{label}</div>
      <div style={{ fontSize: highlight ? 20 : 15, fontWeight: highlight ? 700 : 400 }}>{value}</div>
    </div>
  )
}

const sectionStyle  = { marginBottom: 24, padding: 16, border: '1px solid #ddd', borderRadius: 4 }
const h3            = { fontSize: 14, marginTop: 0, marginBottom: 10 }
const subheadStyle  = { fontSize: 13, fontWeight: 600, marginBottom: 4 }
const gridStyle     = { display: 'flex', gap: 24, flexWrap: 'wrap', justifyContent: 'flex-start', marginBottom: 8 }
const tableStyle    = { borderCollapse: 'collapse', width: '100%', fontSize: 12, marginTop: 4 }
const th            = { textAlign: 'left', padding: '4px 8px', borderBottom: '1px solid #ccc', fontWeight: 600, background: '#f9f9f9', whiteSpace: 'nowrap' }
const td            = { padding: '4px 8px', borderBottom: '1px solid #eee', verticalAlign: 'top' }
const labelStyle    = { display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 4 }
const btnStyle      = { padding: '6px 18px', fontSize: 13, cursor: 'pointer' }
const noteStyle     = { fontSize: 12, color: '#666', margin: '4px 0' }
const detailsLink   = { fontSize: 12, color: '#0066cc', cursor: 'pointer' }
const tabStyle = (active) => ({
  marginRight: 6, padding: '4px 12px', fontSize: 12, cursor: 'pointer',
  border: active ? '1px solid #333' : '1px solid #ccc',
  borderRadius: 3,
  background: active ? '#333' : '#fff',
  color: active ? '#fff' : '#333',
})
const planCardStyle = (key, selected) => ({
  flex: '1 1 180px',
  border: selected ? '2px solid #333' : '1px solid #ddd',
  borderRadius: 4,
  padding: 12,
  background: selected ? '#fafafa' : '#fff',
  cursor: 'pointer',
})
