import React, { useState, useEffect, useCallback } from 'react'
import { getCompute, updateInputs, downloadPdf, downloadLargePdf } from '../api'


// ── Tooltip copy ─────────────────────────────────────────────────────────────
// Exact copy approved by product — do not paraphrase.
const TIPS = {
  requiredToSell: "These repairs aren't about making money. Most buyers\u2019 lenders or basic safety rules won\u2019t overlook them, so fixing them is what lets your home sell to a typical buyer at all. They\u2019re in every plan because they aren\u2019t really optional.",
  enablesSale:    "Fixing this mostly removes a discount a buyer would otherwise demand, rather than adding value on top. Skipping it can lower your price or, for serious issues, cost you buyers whose lender won\u2019t approve the home as-is.",
  optionalValue:  "Not required to sell. These are updates that tend to help your home sell better or for more. You choose which are worth it.",
  valueReturn:    "Roughly how much of this update\u2019s cost typically comes back in your sale price, based on regional cost-vs-value data. Over 100% means it tends to return more than it costs.",
  planROI:        "For every dollar this plan spends on improvements, this is what comes back in sale price. A negative number is normal for plans with required repairs, those exist to make the sale possible, not to profit.",
  valueLiftCapped:"We limited the projected price to what comparable renovated homes in your area actually sell for. Improvements can\u2019t push your price above what the market supports.",
  belowROI:       "This item returns less at sale than it costs to do, so it\u2019s not in the recommended plan. You can still add it, but it won\u2019t pay for itself.",
  getChecked:     "We don\u2019t have enough to estimate this reliably, so the honest move is to have a professional look before deciding, rather than us guessing a cost.",
  investorPath:   "Homes with this issue usually can\u2019t be bought with a normal mortgage, so they tend to sell to a cash investor for less. Fixing it before listing keeps your home open to all buyers. Selling as-is is a real choice, we\u2019re just showing you the difference.",
}

// ── Tooltip component — hover (desktop) + tap (mobile) ───────────────────────
function Tip({ id }) {
  const [open, setOpen] = React.useState(false)
  const text = TIPS[id]
  if (!text) return null

  function toggle(e) {
    e.stopPropagation()
    setOpen(v => {
      if (!v) {
        // Close on next outside click
        setTimeout(() => document.addEventListener('click', () => setOpen(false), { once: true }), 0)
      }
      return !v
    })
  }

  return (
    <span style={{ position: 'relative', display: 'inline-block', verticalAlign: 'middle' }}>
      <span
        role="button"
        tabIndex={0}
        aria-label="What does this mean?"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onClick={toggle}
        onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && toggle(e)}
        className="no-print"
        style={{
          cursor: 'help',
          marginLeft: 4,
          color: '#9ca3af',
          fontSize: 13,
          lineHeight: 1,
          userSelect: 'none',
          display: 'inline-block',
        }}
      >ⓘ</span>
      {open && (
        <span style={{
          position: 'absolute',
          bottom: 'calc(100% + 6px)',
          left: 0,
          zIndex: 9999,
          background: '#1f2937',
          color: '#f3f4f6',
          fontSize: 12,
          lineHeight: 1.55,
          padding: '9px 12px',
          borderRadius: 6,
          width: 'min(260px, 85vw)',
          boxShadow: '0 4px 16px rgba(0,0,0,0.25)',
          whiteSpace: 'normal',
          pointerEvents: 'none',
        }}>
          {text}
        </span>
      )}
    </span>
  )
}

const PLAN_LABELS = {
  leaner:        'Leaner',
  recommended:   'Recommended',
  do_everything: 'Do Everything',
}

const PLAN_DESCRIPTIONS = {
  leaner:        'Required-to-sell items only.',
  recommended:   'Required + improvements that pay back ≥ 75% at sale.',
  do_everything: 'Every actionable item.',
}

const PATH_LABELS = {
  repair:   'Repair',
  replace:  'Replace',
  credit:   'Buyer credit',
  leave:    'Leave as-is',
  upgrade:  'Refresh',
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

function itemCostMid(item) {
  if (item.better_value === 'replace') return item.cost_mid_replace || 0
  return item.cost_mid_repair || item.cost_mid_replace || 0
}

// ── Skip reason for not-included items ──────────────────────────────────────

function skipReason(item, planLevel) {
  if (item.better_value === 'leave')     return 'Good condition — no action needed'
  if (item.recent_replacement)            return 'Recently replaced — no action needed'
  if (!item.condition_detected)           return 'No defect detected'
  if (planLevel === 'leaner')             return 'Leaner plan includes required-to-sell items only'
  if (item.recoup_pct != null && item.recoup_pct < 75)
    return `Below ROI threshold — ${item.recoup_pct?.toFixed(0)}% of cost returns at sale`
  return `Below ROI threshold for this plan`
}

// ── Live net delta computation ───────────────────────────────────────────────
// Approximation: delta from a base plan when items are added/removed or costs change.
// Commission impact on sale-price delta is second-order (~5.5% of recoup delta) and
// intentionally omitted to keep the client-side formula simple. Hit "Apply and
// recompute" for the exact backend number.

// V6A: commissionRate (decimal, e.g. 0.06) and transferTaxRate (e.g. 0.0037) are needed
// because repair-item uplift lands in the sale price, which is subject to both taxes.
// Net change from an item = -cost + uplift*(1 - commissionRate - transferTaxRate)
// => factor becomes (1 - recoup*(1-commissionRate-transferTaxRate)) rather than (1-recoup).
// V6B: payoff changes are dollar-for-dollar shifts in net; track delta vs base.
function computeLiveNet(
  baseNet, repairTable, basePlanIds, effectiveIds, customCosts,
  commissionRate = 0, transferTaxRate = 0,
  payoffTotal = 0, basePayoffTotal = 0
) {
  const upliftFactor = 1 - commissionRate - transferTaxRate
  let delta = 0
  for (const row of repairTable) {
    const cid = row.component_id
    const defaultMid = itemCostMid(row)
    const recoup = (row.recoup_pct || 0) / 100
    const wasIn = basePlanIds.has(cid)
    const isIn  = effectiveIds.has(cid)
    // A6: net impact of each dollar of cost = -(1) + recoup*upliftFactor
    const netCostFactor = 1 - recoup * upliftFactor

    if (row.in_floor) {
      // Floor items can't be toggled, but cost edits still flow to net
      if (wasIn && isIn && customCosts[cid] != null) {
        delta += (defaultMid - customCosts[cid]) * netCostFactor
      }
      continue
    }

    const usedCost = customCosts[cid] != null ? customCosts[cid] : defaultMid

    if (!wasIn && isIn) {
      delta -= usedCost * netCostFactor
    } else if (wasIn && !isIn) {
      delta += defaultMid * netCostFactor
    } else if (wasIn && isIn && customCosts[cid] != null) {
      delta += (defaultMid - customCosts[cid]) * netCostFactor
    }
  }
  // V6B: payoff is dollar-for-dollar (no commission/tax applies to it)
  delta -= (payoffTotal - basePayoffTotal)
  return (baseNet || 0) + delta
}

// ── Repair plan split ────────────────────────────────────────────────────────

function buildRepairPlan(repairTable, floorResult, effectiveIds) {
  if (!repairTable?.length) return { floorItems: [], discretionary: [], notIncluded: [] }

  const floorIds  = new Set((floorResult?.items || []).map(i => i.component_id))
  const floorMeta = Object.fromEntries((floorResult?.items || []).map(i => [i.component_id, i]))

  const floorItems = [], discretionary = [], upgradeItems = [], notIncluded = []

  for (const row of repairTable) {
    // Mirror backend gate: severity "none" = good condition, not a repair candidate.
    // This filters stored results that predate the backend fix.
    if ((row.severity_detected == null || row.severity_detected === 'none')
        && !row.in_floor && row.better_value !== 'upgrade') continue

    const cid       = row.component_id
    const inFloor   = row.in_floor || floorIds.has(cid)  // belt-and-suspenders: row field + floor?.items
    const isUpgrade = row.better_value === 'upgrade'

    if (inFloor && !isUpgrade) {
      floorItems.push({ ...row, floor_reason: floorMeta[cid]?.reason || 'required' })
    } else if (isUpgrade) {
      // Upgrade rows: always in their own section, checkable
      upgradeItems.push(row)
    } else if (effectiveIds.has(cid)) {
      discretionary.push(row)
    } else if (row.better_value !== 'leave') {
      notIncluded.push(row)
    }
  }

  return { floorItems, discretionary, upgradeItems, notIncluded }
}

// ── Inline cost cell ─────────────────────────────────────────────────────────

function CostCell({ item, customCosts, editingCost, setEditingCost, onCostSave }) {
  const cid      = item.component_id
  const hasCustom = customCosts[cid] != null
  const loField  = item.better_value === 'replace' ? item.replace_low  : item.repair_low
  const hiField  = item.better_value === 'replace' ? item.replace_high : item.repair_high

  if (editingCost === cid) {
    return (
      <input
        type="number"
        defaultValue={customCosts[cid] || itemCostMid(item) || ''}
        style={{ width: 90, fontSize: 12, padding: '2px 4px' }}
        autoFocus
        onBlur={e => { onCostSave(cid, e.target.value); setEditingCost(null) }}
        onKeyDown={e => { if (e.key === 'Enter') e.target.blur() }}
      />
    )
  }

  return (
    <span
      onClick={() => setEditingCost(cid)}
      title="Click to enter your own quote"
      style={{ cursor: 'pointer', textDecorationLine: 'underline', textDecorationStyle: 'dotted', fontSize: 12 }}
    >
      {hasCustom
        ? <><strong>{fmt(customCosts[cid])}</strong><span style={{ color: '#2563eb', fontSize: 11 }}> (your quote)</span></>
        : fmtRange(loField, hiField)
      }
    </span>
  )
}

// ── Component ────────────────────────────────────────────────────────────────

export default function ResultsStep({ sessionId }) {
  const [result,          setResult]          = useState(null)
  const [loading,         setLoading]         = useState(true)
  const [error,           setError]           = useState(null)
  const [commission,      setCommission]      = useState(6)
  const [payoffPrimary,   setPayoffPrimary]   = useState(0)
  const [payoffSecondary, setPayoffSecondary] = useState(0)
  const [payoffOther,     setPayoffOther]     = useState(0)
  const [knobDirty,       setKnobDirty]       = useState(false)
  const [applying,        setApplying]        = useState(false)
  const [selectedPlan,    setSelectedPlan]    = useState('recommended')
  // Live plan builder state
  const [customItems,     setCustomItems]     = useState(null)   // null = use plan defaults
  const [customCosts,     setCustomCosts]     = useState({})     // cid -> number
  const [editingCost,     setEditingCost]     = useState(null)   // cid | null

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


  // Reset custom items when plan tab changes
  useEffect(() => { setCustomItems(null) }, [selectedPlan])

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
      setCustomItems(null)
      setCustomCosts({})
    } catch (err) {
      setError(err.message)
    } finally {
      setApplying(false)
    }
  }

  // Toggle item in/out of custom plan
  function toggleItem(cid) {
    setCustomItems(prev => {
      const base = prev ?? new Set(plans[selectedPlan]?.included_items || [])
      const next = new Set(base)
      if (next.has(cid)) next.delete(cid); else next.add(cid)
      return next
    })
  }

  // Save a custom cost quote
  function handleCostSave(cid, rawVal) {
    const n = parseFloat(rawVal)
    if (!isNaN(n) && n > 0) {
      setCustomCosts(prev => ({ ...prev, [cid]: n }))
    } else if (rawVal === '' || rawVal === '0') {
      setCustomCosts(prev => { const next = { ...prev }; delete next[cid]; return next })
    }
  }

  const [pdfLoading, setPdfLoading] = React.useState(false)
  const [pdfError,   setPdfError]   = React.useState(null)

  async function handleDownloadPdf() {
    setPdfLoading(true)
    setPdfError(null)
    try {
      await downloadPdf(sessionId, {
        planKey:     selectedPlan,
        customItems: customItems,   // null = use plan defaults
        customCosts: customCosts,
        liveNet:     liveNet,
      })
    } catch (err) {
      setPdfError(err.message)
    } finally {
      setPdfLoading(false)
    }
  }

  const [largePdfLoading, setLargePdfLoading] = React.useState(false)
  const [largePdfError,   setLargePdfError]   = React.useState(null)

  async function handleDownloadLargePdf() {
    setLargePdfLoading(true)
    setLargePdfError(null)
    try {
      await downloadLargePdf(sessionId, {
        planKey:     selectedPlan,
        customItems: customItems,
        customCosts: customCosts,
        liveNet:     liveNet,
      })
    } catch (err) {
      setLargePdfError(err.message)
    } finally {
      setLargePdfLoading(false)
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

  const isUnderwater = planKeys.length > 0 &&
    planKeys.every(k => (plans[k]?.net_proceeds?.net_proceeds ?? 0) < 0)

  const selPlan      = plans[selectedPlan] || {}
  const selNet       = selPlan.net_proceeds || {}
  // Lender gate: only populated when a major lender-blocking item
  // with a hard-stop detected severity is in this plan's floor.
  const lenderGate   = selPlan.lender_gate || null
  const basePlanIds  = new Set(selPlan.included_items || [])
  // Belt-and-suspenders: use floor?.items AND row.in_floor on repair_table rows.
  // If floor?.items is stale or empty, row.in_floor is the authoritative source.
  const floorIds     = new Set([
    ...(floor?.items || []).map(i => i.component_id),
    ...(repair || []).filter(r => r.in_floor).map(r => r.component_id),
  ])

  // effectiveIds: floor items always in, then custom or plan defaults for the rest
  const planNonFloor = new Set([...(selPlan.included_items || [])].filter(id => !floorIds.has(id)))
  const customNonFloor = customItems  // null or a Set
  const effectiveNonFloor = customNonFloor ?? planNonFloor
  const effectiveIds  = new Set([...floorIds, ...effectiveNonFloor])
  const isCustomized  = customItems !== null &&
    (customItems.size !== planNonFloor.size ||
     [...customItems].some(id => !planNonFloor.has(id)))

  const baseNet  = selNet.net_proceeds ?? 0
  // V6B: base payoff from the stored result (before any live knob change)
  const si = result.seller_inputs || {}
  const basePayoffTotal = si.payoff_primary != null
    ? (si.payoff_primary || 0) + (si.payoff_secondary || 0) + (si.payoff_other || 0)
    : (si.mortgage_payoff || 0)
  const SC_TRANSFER_TAX = 0.0037  // South Carolina deed recording / transfer tax
  const liveNet  = computeLiveNet(
    baseNet, repair, basePlanIds, effectiveIds, customCosts,
    commission / 100, SC_TRANSFER_TAX,
    payoffTotal, basePayoffTotal
  )
  const netDelta = liveNet - baseNet
  const hasCustomCosts = Object.keys(customCosts).length > 0

  const { floorItems, discretionary, upgradeItems, notIncluded } =
    buildRepairPlan(repair, floor, effectiveIds)

  return (
    <div>
      {/* ── Print-only header ── */}
      <div className="print-only" style={{ display: 'none', marginBottom: 20, paddingBottom: 14, borderBottom: '2px solid #000' }}>
        <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 2 }}>
          {result.address || 'Pre-Listing Decision Report'}
        </div>
        <div style={{ fontSize: 12, color: '#444', marginBottom: 10 }}>
          {new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })}
        </div>
        <div style={{ display: 'flex', gap: 28, flexWrap: 'wrap', fontSize: 13, marginBottom: 10 }}>
          <div><strong>As-is value (mid):</strong> {fmt(val.mid)}</div>
          <div><strong>Plan:</strong> {PLAN_LABELS[selectedPlan]}</div>
          <div><strong>Est. net proceeds:</strong> {fmt(selNet.net_proceeds)}</div>
          <div><strong>Commission:</strong> {commission}%</div>
          <div><strong>Mortgage payoff:</strong> {fmt(payoffTotal)}</div>
        </div>
        <div style={{ fontSize: 11, color: '#555', lineHeight: 1.6 }}>
          This is a planning estimate, not an appraisal. All figures are based on available comparable
          sales and regional cost data. Confirm exact payoff balances with your lender before making
          decisions. Days-on-market is based on historical averages and will vary with market conditions.
          Time-to-sell is listing to closing only and does not include construction time.
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    marginBottom: 4 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <h2 style={{ fontSize: 16, margin: 0 }}>Report</h2>
          <button className="no-print" onClick={handleDownloadPdf} disabled={pdfLoading}
            style={{ fontSize: 11, padding: '3px 10px', cursor: pdfLoading ? 'default' : 'pointer',
                     border: '1px solid #ccc', borderRadius: 3, background: '#f9f9f9' }}>
            {pdfLoading ? 'Generating PDF…' : 'Download PDF'}
          </button>
          <button className="no-print" onClick={handleDownloadLargePdf} disabled={largePdfLoading}
            style={{ fontSize: 11, padding: '3px 10px', cursor: largePdfLoading ? 'default' : 'pointer',
                     border: '1px solid #ccc', borderRadius: 3, background: '#f9f9f9' }}>
            {largePdfLoading ? 'Generating…' : 'Download large-print PDF'}
          </button>
          {pdfError && (
            <span className="no-print" style={{ fontSize: 11, color: 'red', marginLeft: 8 }}>
              {pdfError}
            </span>
          )}
          {largePdfError && (
            <span className="no-print" style={{ fontSize: 11, color: 'red', marginLeft: 8 }}>
              {largePdfError}
            </span>
          )}
        </div>
        <span className="no-print" style={{ fontSize: 11, color: '#aaa', fontFamily: 'monospace' }}
              title='Copy this ID to resume the session later'>
          session: {sessionId}
        </span>
      </div>

      {/* ── Valuation ── */}
      <section style={sectionStyle}>
        <h3 style={h3}>As-is value estimate</h3>
        <div style={gridStyle}>
          <Stat label="Low"  value={fmt(val.low)} />
          <Stat label="Mid"  value={fmt(val.mid)} highlight />
          <Stat label="High" value={fmt(val.high)} />
          {val.avm_avg   && <Stat label="AVM avg"    value={fmt(val.avm_avg)} />}
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

      {/* ── Underwater ── */}
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
            and review the required items below to check whether any were flagged in error.
          </p>
          <p style={{ fontSize: 12, color: '#888' }}>
            Adjust the payoff amount in the "Adjust" section below if the figure isn't accurate.
          </p>
        </section>
      )}

      {/* ── Plan cards ── */}
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
                style={planCardStyle(selectedPlan === key)}
                className={selectedPlan === key ? 'plan-card plan-card-selected' : 'plan-card'}
                onClick={() => setSelectedPlan(key)}
              >
                <div className="plan-card-label" style={{ fontWeight: 700, marginBottom: 4, fontSize: 13 }}>
                  {PLAN_LABELS[key]}
                </div>
                <div className="plan-card-desc" style={{ fontSize: 11, color: '#666', marginBottom: 8 }}>
                  {PLAN_DESCRIPTIONS[key]}
                </div>
                <div className="plan-card-net" style={{ fontSize: 15, fontWeight: 700, color: isNeg ? '#c00' : '#1a7f37' }}>
                  {fmt(net.net_proceeds)}
                </div>
                {p.value_lift_capped > 0 && (
                  <div style={{ fontSize: 11, color: '#1a7f37', marginTop: 2 }}>
                    +{fmt(p.value_lift_capped)} est. value lift
                    {p.value_lift_cap_binding && (
                      <span style={{ marginLeft: 4, color: '#b45309', cursor: 'default' }}>
                        ⚑ value lift capped<Tip id="valueLiftCapped" />
                      </span>
                    )}
                  </div>
                )}
                {p.plan_roi_pct != null && (
                  <div style={{ fontSize: 11, color: p.plan_roi_pct >= 0 ? '#1a7f37' : '#c00', marginTop: 2 }}>
                    Plan ROI: {p.plan_roi_pct > 0 ? '+' : ''}{p.plan_roi_pct}%
                    <Tip id="planROI" />
                  </div>
                )}
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
        <p style={caveatNote}>
          Days-on-market is based on historical averages and seasonality.
          A hot or slow market will shift this significantly.
        </p>
        <p style={caveatNote}>
          Time-to-sell is listing to closing only. It does not include time to complete
          major construction — your actual carrying costs will be higher while work is underway.
        </p>
      </section>

      {/* ── Repair plan ── */}
      <section style={sectionStyle}>
        {/* Plan tabs + live net bar */}
        <div className="no-print" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, marginBottom: 14 }}>
          <div>
            {planKeys.map(key => (
              <button key={key}
                style={tabStyle(key === selectedPlan)}
                onClick={() => setSelectedPlan(key)}>
                {PLAN_LABELS[key]}
              </button>
            ))}
          </div>

          {/* Live net proceeds readout */}
          <div style={liveNetBand(netDelta, isCustomized || hasCustomCosts)}>
            <span style={{ fontSize: 11, color: '#555', marginRight: 8 }}>
              {isCustomized || hasCustomCosts ? 'Custom plan — est. net:' : `${PLAN_LABELS[selectedPlan]} est. net:`}
            </span>
            <span style={{ fontSize: 15, fontWeight: 700, color: liveNet < 0 ? '#c00' : '#1a7f37' }}>
              {fmt(liveNet)}
            </span>
            {(isCustomized || hasCustomCosts) && netDelta !== 0 && (
              <span style={{ fontSize: 11, color: netDelta > 0 ? '#1a7f37' : '#c00', marginLeft: 8 }}>
                ({netDelta > 0 ? '+' : ''}{fmt(netDelta)} vs plan)
              </span>
            )}
            {(isCustomized || hasCustomCosts) && (
              <button
                style={{ marginLeft: 12, fontSize: 11, background: 'none', border: '1px solid #ccc', borderRadius: 3, padding: '2px 8px', cursor: 'pointer' }}
                onClick={() => { setCustomItems(null); setCustomCosts({}) }}
              >
                Reset to plan
              </button>
            )}
          </div>
        </div>

        <p className="no-print" style={{ fontSize: 11, color: '#888', marginTop: -8, marginBottom: 14 }}>
          Check or uncheck items to build your own plan. Click any cost to enter a real quote.
          {(isCustomized || hasCustomCosts) && ' Live estimate is approximate — use "Apply and recompute" below for the exact number.'}
        </p>

        {/* ── Section 1: Required to sell ── */}
        {floorItems.length > 0 && (
          <div style={{ marginBottom: 24 }}>
            <div className="section-head" style={sectionHeadStyle('#7c2d12', '#fef3c7', '⚠')}>
              Required to sell<Tip id="requiredToSell" /> — {floorItems.length} item{floorItems.length !== 1 ? 's' : ''}
            </div>
            <p style={{ fontSize: 12, color: '#78350f', margin: '6px 0 10px' }}>
              These must be addressed before listing. Lenders require them fixed before approving a buyer's loan,
              or they are safety issues that will be called out in the buyer's inspection.
              They are included in every plan.
            </p>
            <table style={tableStyle}>
              <thead>
                <tr>
                  <th style={th}>Component</th>
                  <th style={th}>Reason required</th>
                  <th style={th}>Rec. action</th>
                  <th style={th} className="num" title="Click any cost to enter your real quote">Cost estimate ✎</th>
                  <th style={th}>Condition</th>
                  <th style={th}>Note</th>
                </tr>
              </thead>
              <tbody>
                {floorItems.map((item, i) => (
                  <tr key={i} style={{ background: i % 2 === 0 ? '#fffbeb' : '#fff' }}>
                    <td style={{ ...td, fontWeight: 600 }}>{item.display_name}</td>
                    <td style={{ ...td, fontSize: 11, color: '#92400e' }}>{item.floor_reason}</td>
                    <td style={{ ...td, fontWeight: 500 }}>{PATH_LABELS[item.better_value] || item.better_value}</td>
                    <td style={td} className="num">
                      <CostCell
                        item={item}
                        customCosts={customCosts}
                        editingCost={editingCost}
                        setEditingCost={setEditingCost}
                        onCostSave={handleCostSave}
                      />
                    </td>
                    <td style={{ ...td, fontSize: 11, color: '#555' }}>{item.condition_detected || '—'}</td>
                    <td style={{ ...td, fontSize: 11, color: '#777' }}>{item.notes || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ fontSize: 12, color: '#555', marginTop: 6 }}>
              Required-to-sell total: <strong>{fmtRange(floor.cost_low, floor.cost_high)}</strong>
              {floor.cost_mid ? ` (mid ${fmt(floor.cost_mid)})` : ''}
            </div>

            {/* Lender gate: two-path choice for major financing-blocking items */}
            {lenderGate && (
              <div style={{
                marginTop: 16,
                padding: '14px 16px',
                background: '#fafafa',
                border: '1px solid #e5e7eb',
                borderRadius: 6,
                fontSize: 13,
              }}>
                <div style={{ fontWeight: 600, marginBottom: 8, color: '#374151' }}>
                  Why these repairs matter for your buyer pool<Tip id="investorPath" />
                </div>
                <p style={{ margin: '0 0 10px', color: '#4b5563', lineHeight: 1.5 }}>
                  Homes with active foundation moisture, roof leaks, or serious electrical issues
                  usually can&apos;t be purchased with a conventional mortgage, FHA, or VA loan —
                  because the lender requires the issue resolved before they&apos;ll fund the loan.
                  That means most buyers can&apos;t purchase as-is, so the home tends to sell
                  to a cash investor at a lower price.
                  Addressing these before listing keeps your home open to all buyers.
                </p>
                <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 10 }}>
                  <div style={{
                    flex: 1, minWidth: 160,
                    padding: '10px 14px',
                    background: '#f0fdf4',
                    border: '1px solid #bbf7d0',
                    borderRadius: 5,
                  }}>
                    <div style={{ fontSize: 11, color: '#166534', fontWeight: 600, marginBottom: 3 }}>
                      REPAIRED — financed buyers included
                    </div>
                    <div style={{ fontSize: 18, fontWeight: 700, color: '#15803d' }}>
                      {fmt(lenderGate.retail_price)}
                    </div>
                    <div style={{ fontSize: 11, color: '#4b5563', marginTop: 3 }}>
                      Full buyer pool, retail comp pricing
                    </div>
                  </div>
                  <div style={{
                    flex: 1, minWidth: 160,
                    padding: '10px 14px',
                    background: '#f9fafb',
                    border: '1px solid #d1d5db',
                    borderRadius: 5,
                  }}>
                    <div style={{ fontSize: 11, color: '#6b7280', fontWeight: 600, marginBottom: 3 }}>
                      LEFT AS-IS — cash investors only
                    </div>
                    <div style={{ fontSize: 18, fontWeight: 700, color: '#374151' }}>
                      ~{fmt(lenderGate.investor_price)}
                    </div>
                    <div style={{ fontSize: 11, color: '#6b7280', marginTop: 3 }}>
                      Approx. 75% of retail — investor pricing
                    </div>
                  </div>
                </div>
                <div style={{ fontSize: 12, color: '#6b7280' }}>
                  Estimated gap: <strong style={{ color: '#374151' }}>{fmt(lenderGate.investor_gap)}</strong>
                  {' '}between the two paths.
                  Selling as-is to a cash buyer is a real option — for speed or when repair
                  isn&apos;t feasible. This comparison shows the trade-off so you can choose with
                  full information.
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Section 2: Optional — increases value ── */}
        <div style={{ marginBottom: 20 }}>
          <div className="section-head" style={sectionHeadStyle('#14532d', '#f0fdf4', '↑')}>
            Optional — increases value<Tip id="optionalValue" />
            {discretionary.length > 0
              ? ` — ${discretionary.length} item${discretionary.length !== 1 ? 's' : ''} selected`
              : ' — none selected'}
          </div>
          <p style={{ fontSize: 12, color: '#166534', margin: '6px 0 10px' }}>
            Not required to sell. Included because the value return justifies the spend.
            Uncheck any item to remove it from your plan and see the live net adjust.
          </p>

          {discretionary.length > 0 ? (
            <table style={tableStyle}>
              <thead>
                <tr>
                  <th style={{ ...th, width: 28 }}></th>
                  <th style={th}>Component</th>
                  <th style={th}>Condition</th>
                  <th style={th}>Rec. action</th>
                  <th style={th} className="num" title="Click any cost to enter your real quote">Cost estimate ✎</th>
                  <th style={th}>Value return<Tip id="valueReturn" /></th>
                  <th style={th}>Note</th>
                </tr>
              </thead>
              <tbody>
                {discretionary.map((item, i) => (
                  <tr key={i} style={{ background: i % 2 === 0 ? '#f0fdf4' : '#fff' }}>
                    <td style={{ ...td, textAlign: 'center' }}>
                      <input type="checkbox" checked
                        onChange={() => toggleItem(item.component_id)}
                        className="no-print"
                        style={{ cursor: 'pointer' }} />
                    </td>
                    <td style={{ ...td, fontWeight: 500 }}>{item.display_name}</td>
                    <td style={{ ...td, fontSize: 11, color: '#555' }}>{item.condition_detected || '—'}</td>
                    <td style={td}>{PATH_LABELS[item.better_value] || item.better_value}</td>
                    <td style={td} className="num">
                      <CostCell
                        item={item}
                        customCosts={customCosts}
                        editingCost={editingCost}
                        setEditingCost={setEditingCost}
                        onCostSave={handleCostSave}
                      />
                    </td>
                    <td style={{ ...td, fontSize: 11 }}>
                      {item.effective_recoup_label || `${item.recoup_pct?.toFixed(0)}%`}
                      {item.effective_recoup_label === 'enables sale / removes discount' && <Tip id="enablesSale" />}
                    </td>
                    <td style={{ ...td, fontSize: 11, color: '#777' }}>
                      {item.notes || '—'}
                      {/inspect|get this checked/i.test(item.notes || '') && <Tip id="getChecked" />}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p style={{ fontSize: 12, color: '#888', fontStyle: 'italic' }}>
              No optional items selected. Check items below to add them.
            </p>
          )}
        </div>

        {/* ── Section 3: Not included ── */}
        {notIncluded.length > 0 && (
          <details>
            <summary style={detailsLink}>
              {notIncluded.length} item{notIncluded.length !== 1 ? 's' : ''} not in this plan — check to add
            </summary>
            <table style={{ ...tableStyle, marginTop: 8 }}>
              <thead>
                <tr>
                  <th style={{ ...th, width: 28 }}></th>
                  <th style={th}>Component</th>
                  <th style={th}>Condition</th>
                  <th style={th}>Why not included</th>
                  <th style={th} className="num" title="Click any cost to enter your real quote">Cost estimate ✎</th>
                  <th style={th}>Value return</th>
                </tr>
              </thead>
              <tbody>
                {notIncluded.map((item, i) => {
                  const reason = skipReason(item, selectedPlan)
                  const label  = item.effective_recoup_label || (item.recoup_pct != null ? `${item.recoup_pct?.toFixed(0)}%` : '—')
                  return (
                  <tr key={i}>
                    <td style={{ ...td, textAlign: 'center' }}>
                      <input type="checkbox" checked={false}
                        onChange={() => toggleItem(item.component_id)}
                        className="no-print"
                        style={{ cursor: 'pointer' }} />
                    </td>
                    <td style={td}>{item.display_name}</td>
                    <td style={{ ...td, fontSize: 11 }}>{item.condition_detected || '—'}</td>
                    <td style={{ ...td, fontSize: 11, color: '#888' }}>
                      {reason}
                      {reason.startsWith('Below ROI') && <Tip id="belowROI" />}
                      {/inspect|get this checked/i.test(reason) && <Tip id="getChecked" />}
                    </td>
                    <td style={td} className="num">
                      <CostCell
                        item={item}
                        customCosts={customCosts}
                        editingCost={editingCost}
                        setEditingCost={setEditingCost}
                        onCostSave={handleCostSave}
                      />
                    </td>
                    <td style={{ ...td, fontSize: 11 }}>
                      {label}
                      {label === 'enables sale / removes discount' && <Tip id="enablesSale" />}
                    </td>
                  </tr>
                  )
                })}
              </tbody>
            </table>
          </details>
        )}

        {/* ── Upgrade / quick refresh items ── */}
        {upgradeItems.length > 0 && (
          <div style={{ marginBottom: 24 }}>
            <div className="section-head" style={sectionHeadStyle('#065f46', '#d1fae5', '✦')}>
              Quick refresh — optional, often strong return ({upgradeItems.length})
            </div>
            <p style={{ fontSize: 12, color: '#555', marginTop: 0, marginBottom: 8 }}>
              Cosmetic updates, not defects. Low cost, high buyer appeal.
            </p>
            <table style={tableStyle}>
              <thead><tr>
                <th style={th}>Item</th>
                <th style={th}>Est. cost</th>
                <th style={th}>Recoup %</th>
              </tr></thead>
              <tbody>
                {upgradeItems.map((item, i) => (
                  <tr key={i}>
                    <td style={{ ...td, fontWeight: 500 }}>{item.display_name}</td>
                    <td style={td} className="num"><CostCell item={item} customCosts={customCosts}
                      editingCost={editingCost} setEditingCost={setEditingCost}
                      onCostSave={handleCostSave} /></td>
                    <td style={td}>{item.recoup_pct != null ? `${item.recoup_pct}%` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {floorItems.length === 0 && discretionary.length === 0 && notIncluded.length === 0 && (
          <p style={{ fontSize: 13, color: '#888' }}>
            No repair items found. Make sure photos have been tagged and the questionnaire submitted.
          </p>
        )}
      </section>

      {/* ── Print footer (fixed, appears on every printed page) ── */}
      <div className="print-footer" style={{ display: 'none' }}>
        <span>{result.address || 'Pre-Listing Decision Report'}</span>
        <span>Pre-Listing Decision Tool</span>
      </div>

      {/* ── Adjust inputs ── */}
      <section className="no-print" style={sectionStyle}>
        <h3 style={h3}>Adjust inputs</h3>
        <p style={noteStyle}>
          Changing these recalculates the exact net proceeds from the backend.
          The live estimate above is an approximation — use this for the precise number.
        </p>

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
            Include all balances. Forgetting a HELOC or lien is the most common source of a wrong net number.
          </p>
          {[
            { label: 'Primary mortgage',              val: payoffPrimary,   set: setPayoffPrimary },
            { label: 'Second mortgage / HELOC',       val: payoffSecondary, set: setPayoffSecondary },
            { label: 'Liens, unpaid taxes, or other', val: payoffOther,     set: setPayoffOther },
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

// ── Sub-components ───────────────────────────────────────────────────────────

function Stat({ label, value, highlight }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 11, color: '#888' }}>{label}</div>
      <div style={{ fontSize: highlight ? 20 : 15, fontWeight: highlight ? 700 : 400 }}>{value}</div>
    </div>
  )
}

function sectionHeadStyle(color, bg, icon) {
  return {
    fontSize: 13,
    fontWeight: 700,
    color,
    background: bg,
    borderRadius: 3,
    padding: '5px 10px',
    marginBottom: 0,
    display: 'inline-block',
  }
}

// ── Styles ───────────────────────────────────────────────────────────────────

const sectionStyle  = { marginBottom: 24, padding: 16, border: '1px solid #ddd', borderRadius: 4 }
const h3            = { fontSize: 14, marginTop: 0, marginBottom: 10 }
const gridStyle     = { display: 'flex', gap: 24, flexWrap: 'wrap', justifyContent: 'flex-start', marginBottom: 8 }
const tableStyle    = { borderCollapse: 'collapse', width: '100%', fontSize: 12, marginTop: 4 }
const th            = { textAlign: 'left', padding: '4px 8px', borderBottom: '1px solid #ccc', fontWeight: 600, background: '#f9f9f9', whiteSpace: 'nowrap' }
const td            = { padding: '4px 8px', borderBottom: '1px solid #eee', verticalAlign: 'top' }
const labelStyle    = { display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 4 }
const btnStyle      = { padding: '6px 18px', fontSize: 13, cursor: 'pointer' }
const noteStyle     = { fontSize: 12, color: '#666', margin: '4px 0' }
const caveatNote    = { fontSize: 11, color: '#999', margin: '4px 0' }
const detailsLink   = { fontSize: 12, color: '#0066cc', cursor: 'pointer' }

const tabStyle = (active) => ({
  marginRight: 6, padding: '4px 12px', fontSize: 12, cursor: 'pointer',
  border: active ? '1px solid #333' : '1px solid #ccc',
  borderRadius: 3,
  background: active ? '#333' : '#fff',
  color: active ? '#fff' : '#333',
})

const planCardStyle = (selected) => ({
  flex: '1 1 180px',
  border: selected ? '2px solid #333' : '1px solid #ddd',
  borderRadius: 4,
  padding: 12,
  background: selected ? '#fafafa' : '#fff',
  cursor: 'pointer',
})

const liveNetBand = (delta, isCustomized) => ({
  display: 'flex',
  alignItems: 'center',
  background: isCustomized ? '#eff6ff' : '#f9f9f9',
  border: isCustomized ? '1px solid #bfdbfe' : '1px solid #e5e7eb',
  borderRadius: 4,
  padding: '5px 12px',
  gap: 4,
})
