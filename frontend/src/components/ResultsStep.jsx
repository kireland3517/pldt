import React, { useState, useEffect, useCallback } from 'react'
import { getCompute, updateInputs } from '../api'

const PLAN_LABELS = {
  leaner:       'Leaner — minimum required',
  recommended:  'Recommended',
  do_everything:'Do everything',
  scorecard:    'Scorecard',
}

function fmt(n) {
  if (n == null) return '—'
  return '$' + Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 })
}

export default function ResultsStep({ sessionId }) {
  const [result, setResult]         = useState(null)
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState(null)
  const [commission, setCommission] = useState(6)
  const [payoff, setPayoff]         = useState(0)
  const [knobDirty, setKnobDirty]   = useState(false)
  const [applying, setApplying]     = useState(false)

  const load = useCallback(async (refresh = false) => {
    setLoading(true)
    setError(null)
    try {
      const r = await getCompute(sessionId, refresh)
      setResult(r)
      // Pre-populate knobs from stored session values on first load
      if (!refresh) {
        if (r.commission_rate) setCommission(Math.round(r.commission_rate * 100 * 10) / 10)
        const bal = r.seller_inputs?.mortgage_payoff
        if (bal != null && bal > 0) setPayoff(bal)
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
        seller_inputs: { mortgage_payoff: payoff },
      })
      await load(true)
      setKnobDirty(false)
    } catch (err) {
      setError(err.message)
    } finally {
      setApplying(false)
    }
  }

  if (loading) return <p>Computing results...</p>
  if (error) return <p style={{ color: 'red' }}>Error: {error}</p>
  if (!result) return null

  const val   = result.valuation || result.as_is_range || {}
  const plans = result.plans || {}
  const floor = result.floor || {}
  const planKeys = ['leaner', 'recommended', 'do_everything'].filter(k => plans[k])

  return (
    <div>
      <h2 style={{ fontSize: 16, marginBottom: 4 }}>Report</h2>
      <p style={{ fontSize: 12, color: '#888', marginBottom: 20 }}>Session {sessionId}</p>

      {/* Valuation */}
      <section style={sectionStyle}>
        <h3 style={h3}>As-is valuation</h3>
        <div style={gridStyle}>
          <Stat label="Low"  value={fmt(val.low)} />
          <Stat label="Mid"  value={fmt(val.mid)} highlight />
          <Stat label="High" value={fmt(val.high)} />
          <Stat label="AVM avg" value={fmt(val.avm_avg)} />
          <Stat label="Confidence" value={val.confidence ? `${(val.confidence * 100).toFixed(0)}%` : '—'} />
        </div>
        {val.note && <p style={{ fontSize: 12, color: '#666', marginTop: 8 }}>{val.note}</p>}

        {val.comp_detail && (
          <details style={{ marginTop: 12 }}>
            <summary style={{ fontSize: 12, cursor: 'pointer' }}>Comp detail</summary>
            <table style={tableStyle}>
              <thead><tr>
                <th style={th}>Address</th><th style={th}>Price</th><th style={th}>$/sqft actual</th>
                <th style={th}>Weight</th><th style={th}>Note</th>
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

      {/* Floor items */}
      {floor.items?.length > 0 && (
        <section style={sectionStyle}>
          <h3 style={h3}>Required work (floor items — {floor.item_count})</h3>
          <table style={tableStyle}>
            <thead><tr>
              <th style={th}>Component</th><th style={th}>Reason</th>
              <th style={th}>Path</th><th style={th}>Cost range</th>
            </tr></thead>
            <tbody>
              {floor.items.map((item, i) => (
                <tr key={i}>
                  <td style={td}><code>{item.component_id}</code></td>
                  <td style={td}>{item.reason}</td>
                  <td style={td}>{item.path}</td>
                  <td style={td}>{fmt(item.cost_low)} – {fmt(item.cost_high)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p style={{ fontSize: 12, color: '#555', marginTop: 6 }}>
            Floor total: {fmt(floor.cost_low)} – {fmt(floor.cost_high)} (mid {fmt(floor.cost_mid)})
          </p>
        </section>
      )}

      {/* Plans */}
      <section style={sectionStyle}>
        <h3 style={h3}>Plans</h3>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          {planKeys.map(key => {
            const p = plans[key]
            const net = p.net_proceeds || {}
            return (
              <div key={key} style={planCardStyle(key)}>
                <div style={{ fontWeight: 700, marginBottom: 6, fontSize: 14 }}>
                  {PLAN_LABELS[key] || key}
                </div>
                <div style={{ fontSize: 13, marginBottom: 4 }}>
                  Net proceeds: <strong>{fmt(net.net_proceeds)}</strong>
                </div>
                <div style={{ fontSize: 12, color: '#555' }}>
                  Gross: {fmt(net.gross_sale_price)}<br />
                  Deductions: {fmt(net.total_deductions)}<br />
                  DOM: {p.dom?.estimated_dom} days
                </div>
                {net.line_items && (
                  <details style={{ marginTop: 8 }}>
                    <summary style={{ fontSize: 11, cursor: 'pointer' }}>Line items</summary>
                    {net.line_items.map((li, i) => (
                      <div key={i} style={{ fontSize: 11, display: 'flex', justifyContent: 'space-between', marginTop: 2 }}>
                        <span>{li.label}</span>
                        <span>{fmt(li.amount)}</span>
                      </div>
                    ))}
                  </details>
                )}
              </div>
            )
          })}
        </div>
      </section>

      {/* Live knobs */}
      <section style={sectionStyle}>
        <h3 style={h3}>Adjust</h3>
        <label style={labelStyle}>
          Commission rate: <strong>{commission}%</strong>
          <input type="range" min={1} max={8} step={0.5}
            value={commission}
            onChange={e => { setCommission(+e.target.value); setKnobDirty(true) }}
            style={{ marginLeft: 8, verticalAlign: 'middle' }}
          />
        </label>
        <label style={{ ...labelStyle, marginTop: 10 }}>
          Mortgage payoff: <strong>{fmt(payoff)}</strong>
          <input type="number" min={0} step={1000}
            value={payoff}
            onChange={e => { setPayoff(+e.target.value); setKnobDirty(true) }}
            style={{ marginLeft: 8, padding: '3px 6px', fontSize: 13 }}
          />
        </label>
        {knobDirty && (
          <button style={{ ...btnStyle, marginTop: 8 }} onClick={applyKnobs} disabled={applying}>
            {applying ? 'Recomputing...' : 'Apply and recompute'}
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
const h3            = { fontSize: 14, marginTop: 0, marginBottom: 12 }
const gridStyle     = { display: 'flex', gap: 24, flexWrap: 'wrap', justifyContent: 'flex-start' }
const tableStyle    = { borderCollapse: 'collapse', width: '100%', fontSize: 12, marginTop: 8 }
const th            = { textAlign: 'left', padding: '3px 8px', borderBottom: '1px solid #ccc', fontWeight: 600 }
const td            = { padding: '3px 8px', borderBottom: '1px solid #eee', verticalAlign: 'top' }
const labelStyle    = { display: 'block', fontSize: 13, fontWeight: 500 }
const btnStyle      = { padding: '6px 18px', fontSize: 13, cursor: 'pointer' }
const planCardStyle = (key) => ({
  flex: '1 1 200px',
  border: key === 'recommended' ? '2px solid #333' : '1px solid #ddd',
  borderRadius: 4,
  padding: 12,
  background: key === 'recommended' ? '#fafafa' : '#fff',
})
