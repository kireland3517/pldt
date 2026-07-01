import React, { useState, useEffect, useCallback, useRef } from 'react'
import { getCompute, updateInputs, updateOverride, downloadPdf, downloadLargePdf, refetchMarketData, getCustomPlan } from '../api'


// ── Tooltip copy ─────────────────────────────────────────────────────────────
// Exact copy approved by product — do not paraphrase.
const TIPS = {
  requiredToSell: "These repairs aren't about making money. Most buyers’ lenders or basic safety rules won’t overlook them, so fixing them is what lets your home sell to a typical buyer at all. They’re in every plan because they aren’t really optional.",
  enablesSale:    "Fixing this mostly removes a discount a buyer would otherwise demand, rather than adding value on top. Skipping it can lower your price or, for serious issues, cost you buyers whose lender won’t approve the home as-is.",
  optionalValue:  "Not required to sell. These are updates that tend to help your home sell better or for more. You choose which are worth it.",
  valueReturn:    "Roughly how much of this update’s cost typically comes back in your sale price, based on regional cost-vs-value data. Over 100% means it tends to return more than it costs.",
  planROI:        "For every dollar this plan spends on improvements, this is what comes back in sale price. A negative number is normal for plans with required repairs, those exist to make the sale possible, not to profit.",
  valueLiftCapped:"We limited the projected price to what comparable renovated homes in your area actually sell for. Improvements can’t push your price above what the market supports.",
  belowROI:       "This item returns less at sale than it costs to do, so it’s not in the recommended plan. You can still add it, but it won’t pay for itself.",
  getChecked:     "We don’t have enough to estimate this reliably, so the honest move is to have a professional look before deciding, rather than us guessing a cost.",
  investorPath:   "Homes with this issue usually can’t be bought with a normal mortgage, so they tend to sell to a cash investor for less. Fixing it before listing keeps your home open to all buyers. Selling as-is is a real choice, we’re just showing you the difference.",
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
  const mid      = itemCostMid(item)

  if (editingCost === cid) {
    return (
      <input
        type="number"
        defaultValue={customCosts[cid] || mid || ''}
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
      title="Click to enter your own cost"
      style={{ cursor: 'pointer', textDecorationLine: 'underline', textDecorationStyle: 'dotted', fontSize: 12 }}
    >
      {hasCustom
        ? <><strong>{fmt(customCosts[cid])}</strong><span style={{ color: '#2563eb', fontSize: 11 }}> (edited)</span></>
        : (mid ? fmt(mid) : fmtRange(loField, hiField))
      }
    </span>
  )
}

// ── Stage 2 Step 2: editable price-to-net lines ──────────────────────────────
// Editable set mirrors backend exactly:
//   GLOBAL   (PATCH /inputs):    commission_rate, mortgage_payoff
//   PER-PLAN (PATCH /overrides): _OVERRIDE_LINE_KEYS in compute.py, listed below
// seller_credits / other_seller_costs stay display-only — no UI ever wrote
// them and they are not in _OVERRIDE_LINE_KEYS.

const PER_PLAN_KEYS = new Set([
  'transfer_tax', 'attorney_fee', 'deed_fee', 'cl100',
  'hoa_estoppel', 'repair_cost', 'concessions', 'carrying_cost',
])

// Bug 3 fix (Stage 2 Step 2 bugfix round): mortgage_payoff, seller_credits,
// and other_seller_costs are GLOBAL FACTS in net_proceeds.py — calculated_amount
// is always 0.0 for these (the engine has no way to derive them) and
// override_amount always carries the actual stored value whenever it's
// nonzero. That means override_amount != null does NOT mean "the user
// changed this from a default" for these three keys, it just means "this
// fact currently has a value." Treating them as "edited" mislabels every
// normal session and, worse, would offer a reset that wipes a real payoff
// to $0 as if it were an accidental edit. Exclude them from the
// edited/reset styling entirely — only commission (has a real calculated
// default) and the per-plan lines (have a real calculated baseline) use it.
const GLOBAL_FACT_KEYS = new Set(['mortgage_payoff', 'seller_credits', 'other_seller_costs'])

function NetLineRow({
  li, planLevel, editingLine, setEditingLine,
  commission, setCommission, commissionRef,
  payoffOpen, setPayoffOpen,
  payoffPrimary, setPayoffPrimary,
  payoffSecondary, setPayoffSecondary,
  payoffOther, setPayoffOther,
  saving, commitOverride, commitGlobal, grossPrice,
  resetAllItemCosts, readOnly = false,
}) {
  const isEdited = li.override_amount != null && !GLOBAL_FACT_KEYS.has(li.key)
  const editable = PER_PLAN_KEYS.has(li.key) || li.key === 'commission' || li.key === 'mortgage_payoff'

  const labelEl = (
    <span style={{ fontStyle: isEdited ? 'italic' : 'normal' }}>
      − {li.label}
      {isEdited && (
        <span style={{ color: '#2563eb', fontSize: 10, marginLeft: 4, fontStyle: 'normal' }}>
          ● edited
        </span>
      )}
    </span>
  )

  function resetLine() {
    if (li.key === 'commission') {
      // Derive the default rate from the engine's own calculated_amount /
      // gross_sale_price rather than hard-coding 6% in the frontend, so a
      // future change to the backend default still resets correctly.
      const pct = Math.round((li.calculated_amount / grossPrice) * 1000) / 10
      setCommission(pct)
      commissionRef.current = pct
      commitGlobal({ commission_rate: pct / 100 })
    } else if (li.key === 'mortgage_payoff') {
      setPayoffPrimary(0)
      setPayoffSecondary(0)
      setPayoffOther(0)
      commitGlobal({
        seller_inputs: {
          mortgage_payoff: 0, payoff_primary: 0, payoff_secondary: 0, payoff_other: 0,
        },
      })
    } else if (li.key === 'repair_cost') {
      // Item costs are global across plans (see commitItemCost). Resetting
      // repair_cost on any one tab must clear every item override and revert
      // repair_cost on all three plans, or the "items sum to total" invariant
      // breaks on the tabs you didn't click reset on.
      resetAllItemCosts()
    } else {
      commitOverride(planLevel, li.key, null)
    }
  }

  const resetEl = isEdited && editable && (
    <button
      onClick={resetLine}
      disabled={saving}
      title="Reset to calculated"
      style={{
        border: 'none', background: 'none', cursor: saving ? 'default' : 'pointer',
        color: '#9ca3af', fontSize: 12, marginLeft: 4, padding: 0,
      }}
    >↺</button>
  )

  // ── Commission: dollar line + slider, recomputes on release. Percent
  // label is live-on-drag (reads `commission` state, which already updates
  // on every onChange); dollar amount and net stay release-only via
  // commitGlobal on mouseUp/touchEnd, unchanged.
  if (li.key === 'commission') {
    return (
      <div style={{ marginBottom: 10 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: '#6b7280' }}>
          <span>{labelEl} — {commission.toFixed(1)}%</span>
          <span>({fmt(li.amount)}) {resetEl}</span>
        </div>
        <input
          type="range" min={1} max={8} step={0.5}
          value={commission}
          disabled={saving}
          onChange={e => {
            const v = +e.target.value
            setCommission(v)
            commissionRef.current = v
          }}
          onMouseUp={() => commitGlobal({ commission_rate: commissionRef.current / 100 })}
          onTouchEnd={() => commitGlobal({ commission_rate: commissionRef.current / 100 })}
          style={{ width: '100%', marginTop: 2 }}
        />
      </div>
    )
  }

  // ── Mortgage payoff: dollar line, click to expand 3 sub-fields ──
  if (li.key === 'mortgage_payoff') {
    return (
      <div style={{ marginBottom: 10 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: '#6b7280' }}>
          {labelEl}
          <span>
            <span
              onClick={() => setPayoffOpen(v => !v)}
              title="Click to edit"
              style={{ cursor: 'pointer', textDecorationLine: 'underline', textDecorationStyle: 'dotted' }}
            >
              ({fmt(li.amount)})
            </span> {resetEl}
          </span>
        </div>
        {payoffOpen && (
          <div style={{ display: 'flex', gap: 8, marginTop: 4, flexWrap: 'wrap' }}>
            {[
              { label: 'Primary',      val: payoffPrimary,   set: setPayoffPrimary },
              { label: 'Second/HELOC', val: payoffSecondary, set: setPayoffSecondary },
              { label: 'Liens/other',  val: payoffOther,     set: setPayoffOther },
            ].map(({ label, val, set }) => (
              <input
                key={label} type="number" min={0} step={1000} value={val}
                placeholder={label}
                disabled={saving}
                onChange={e => set(+e.target.value || 0)}
                onBlur={() => commitGlobal({
                  seller_inputs: {
                    mortgage_payoff:  payoffPrimary + payoffSecondary + payoffOther,
                    payoff_primary:   payoffPrimary,
                    payoff_secondary: payoffSecondary,
                    payoff_other:     payoffOther,
                  },
                })}
                style={{ width: 90, fontSize: 11, padding: '2px 4px' }}
              />
            ))}
          </div>
        )}
      </div>
    )
  }

  // ── repair_cost: display only. Edits happen bottom-up from item costs
  // (see CostCell / commitItemCost); this line only shows the sum and, if
  // any item is overridden, a reset that clears all item overrides.
  if (li.key === 'repair_cost') {
    return (
      <div style={{ display: 'flex', justifyContent: 'space-between',
                    fontSize: 12, color: '#6b7280', marginBottom: 4 }}>
        {labelEl}
        <span>({fmt(li.amount)}) {resetEl}</span>
      </div>
    )
  }

  // ── Per-plan overridable lines: click to edit, commit on blur/Enter ──
  if (PER_PLAN_KEYS.has(li.key) && li.key !== 'repair_cost') {
    if (readOnly) {
      return (
        <div style={{ display: 'flex', justifyContent: 'space-between',
                      fontSize: 12, color: '#6b7280', marginBottom: 4 }}>
          {labelEl}
          <span>({fmt(li.amount)})</span>
        </div>
      )
    }
    if (editingLine === li.key) {
      return (
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
          {labelEl}
          <input
            type="number" defaultValue={li.amount} autoFocus
            style={{ width: 80, fontSize: 12, padding: '1px 4px' }}
            onBlur={e => {
              const n = parseFloat(e.target.value)
              setEditingLine(null)
              if (!isNaN(n) && n >= 0) commitOverride(planLevel, li.key, n)
            }}
            onKeyDown={e => { if (e.key === 'Enter') e.target.blur() }}
          />
        </div>
      )
    }
    return (
      <div style={{ display: 'flex', justifyContent: 'space-between',
                    fontSize: 12, color: '#6b7280', marginBottom: 4 }}>
        {labelEl}
        <span>
          <span
            onClick={() => setEditingLine(li.key)}
            title="Click to enter your own amount"
            style={{ cursor: 'pointer', textDecorationLine: 'underline', textDecorationStyle: 'dotted' }}
          >
            ({fmt(li.amount)})
          </span> {resetEl}
        </span>
      </div>
    )
  }

  // ── seller_credits / other_seller_costs: display only, not editable in Step 2 ──
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between',
                  fontSize: 12, color: '#6b7280', marginBottom: 4 }}>
      {labelEl}
      <span>({fmt(li.amount)})</span>
    </div>
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
  const [selectedPlan,    setSelectedPlan]    = useState('recommended')
  // Live plan builder state
  const [customItems,     setCustomItems]     = useState(null)   // null = use plan defaults
  const [customCosts,     setCustomCosts]     = useState({})     // cid -> number
  const [editingCost,     setEditingCost]     = useState(null)   // cid | null
  const [refetching,      setRefetching]      = useState(false)
  // Stage 2 Step 2 — price-to-net line editing state
  const [saving,          setSaving]          = useState(false)
  const [editError,       setEditError]       = useState(null)
  const [editingLine,     setEditingLine]     = useState(null)   // line key being typed into
  const [payoffOpen,      setPayoffOpen]      = useState(false)  // payoff sub-field panel expanded
  const commissionRef = useRef(commission)

  // ── Stage 2 Step 3: Custom tab -- item-set-driven, calls /custom-plan.
  // Deliberately separate from customItems/customCosts above (those feed the
  // standard-tab PDF download machinery and must not be touched here).
  const [customCheckedIds,    setCustomCheckedIds]    = useState(null)   // Set|null; null = not seeded yet
  const [customCostOverrides, setCustomCostOverrides] = useState({})    // {cid: number}
  const [customAddedItems,    setCustomAddedItems]    = useState([])    // [{label, cost, checked}]
  const [customPlan,          setCustomPlan]          = useState(null)  // last good /custom-plan response
  const [customLoading,       setCustomLoading]       = useState(false) // true only before first result
  const [customRecalculating, setCustomRecalculating] = useState(false)
  const [customError,         setCustomError]         = useState(null)
  const [newItemLabel,        setNewItemLabel]        = useState('')
  const [newItemCost,         setNewItemCost]         = useState('')
  const customSeqRef = useRef(0)

  const payoffTotal = payoffPrimary + payoffSecondary + payoffOther

  async function handleRefetchMarket() {
    setRefetching(true)
    try {
      await refetchMarketData(sessionId)
      await load(true)   // triggers recompute with fresh ATTOM data
    } catch (err) {
      setError(err.message)
    } finally {
      setRefetching(false)
    }
  }

  const load = useCallback(async (refresh = false) => {
    setLoading(true)
    setError(null)
    try {
      const r = await getCompute(sessionId, refresh)
      // Auto-refresh if cached result is missing fields added after the
      // session was last computed (e.g. active_listings, sales_history_5yr).
      // Triggers once: after refresh the field exists (possibly []) and stops.
      if (!refresh && r.active_listings === undefined) {
        return load(true)
      }
      setResult(r)
      if (!refresh) {
        if (r.commission_rate) {
          const pct = Math.round(r.commission_rate * 100 * 10) / 10
          setCommission(pct)
          commissionRef.current = pct
        }
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


  // Reset custom items + any line-edit error when plan tab changes
  useEffect(() => { setCustomItems(null); setEditError(null) }, [selectedPlan])

  // Seed the Custom checked-set from Recommended's included_items exactly
  // once. recommended.included_items already contains floor + qualifying
  // optional items (optimizer.py::_items_for_level), so this single
  // assignment reproduces Recommended exactly on first open. Never re-seeds
  // on a later tab switch -- the user's edits persist across tabs. Reads
  // `result` directly (not the later `plans` const) so this hook can sit
  // above the component's early-return guards without violating the Rules
  // of Hooks.
  useEffect(() => {
    const recommendedIds = result?.plans?.recommended?.included_items
    if (customCheckedIds === null && recommendedIds) {
      setCustomCheckedIds(new Set(recommendedIds))
    }
  }, [result, customCheckedIds])

  async function runCustomPlan() {
    if (!customCheckedIds) return
    const seq = ++customSeqRef.current
    if (!customPlan) setCustomLoading(true)
    else setCustomRecalculating(true)
    try {
      const r = await getCustomPlan(sessionId, {
        itemIds:           [...customCheckedIds],
        itemCostOverrides: customCostOverrides,
        addedItems:        customAddedItems.filter(it => it.checked),
      })
      if (seq !== customSeqRef.current) return   // a newer request already landed
      setCustomPlan(r.plan)
      setCustomError(null)
    } catch (err) {
      if (seq !== customSeqRef.current) return
      setCustomError(err.message)
    } finally {
      if (seq === customSeqRef.current) { setCustomLoading(false); setCustomRecalculating(false) }
    }
  }

  useEffect(() => {
    if (selectedPlan !== 'custom' || !customCheckedIds) return
    runCustomPlan()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedPlan, customCheckedIds, customCostOverrides, customAddedItems])

  function toggleCustomItem(cid) {
    setCustomCheckedIds(prev => {
      const next = new Set(prev)
      if (next.has(cid)) next.delete(cid); else next.add(cid)
      return next
    })
  }

  function commitCustomItemCost(cid, rawVal) {
    const n = parseFloat(rawVal)
    setCustomCostOverrides(prev => {
      const next = { ...prev }
      if (!isNaN(n) && n > 0) next[cid] = n; else delete next[cid]
      return next
    })
  }

  function addCustomItem() {
    const cost = parseFloat(newItemCost)
    if (!newItemLabel.trim() || isNaN(cost) || cost <= 0) return
    setCustomAddedItems(prev => [...prev, { label: newItemLabel.trim(), cost, checked: true }])
    setNewItemLabel('')
    setNewItemCost('')
  }

  function toggleAddedItemChecked(idx) {
    setCustomAddedItems(prev => prev.map((it, i) => i === idx ? { ...it, checked: !it.checked } : it))
  }

  function updateAddedItemCost(idx, rawVal) {
    const n = parseFloat(rawVal)
    if (isNaN(n) || n <= 0) return
    setCustomAddedItems(prev => prev.map((it, i) => i === idx ? { ...it, cost: n } : it))
  }

  function removeCustomAddedItem(idx) {
    setCustomAddedItems(prev => prev.filter((_, i) => i !== idx))
  }

  // Stage 2 Step 2 — commit handlers for inline price-to-net edits.
  // On failure, `result` is left untouched (no setResult / no load() call),
  // so the displayed net never goes half-updated or stale. The error shows
  // inline near the "Price to net" header via editError — never through the
  // page-level error state, which would otherwise blank the whole results view.
  async function commitOverride(planLevel, lineKey, amount) {
    setSaving(true)
    setEditError(null)
    try {
      const r = await updateOverride(sessionId, planLevel, lineKey, amount)
      setResult(r)
    } catch (err) {
      setEditError(err.message)
    } finally {
      setSaving(false)
    }
  }

  async function commitGlobal(patch) {
    // Bug 2 fix (Stage 2 Step 2 bugfix round): PATCH /inputs now supports
    // return_result=true, returning the full recomputed shape (same as
    // PATCH /overrides) instead of just {ok}. That lets us setResult() in
    // place here, exactly like commitOverride, with no load()/getCompute()
    // round trip. load()'s setLoading(true) was the source of the full-page
    // "Computing results..." flash on every commission/payoff edit.
    setSaving(true)
    setEditError(null)
    try {
      const r = await updateInputs(sessionId, { ...patch, return_result: true })
      setResult(r)
      setCustomItems(null)
      setCustomCosts({})
      // Custom's source of truth is customPlan from /custom-plan, not `result`
      // -- a global edit (commission, payoff) must re-run /custom-plan so the
      // returned plan reflects the new session-level value. Do NOT call
      // load(true) here; that reloads the standard three-plan result instead.
      if (selectedPlan === 'custom') {
        await runCustomPlan()
      }
    } catch (err) {
      setEditError(err.message)
    } finally {
      setSaving(false)
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

  const val            = result.valuation || result.as_is_range || {}
  const plans          = result.plans     || {}
  const floor          = result.floor     || {}
  const repair         = result.repair_table || []
  const activeListings = result.active_listings   || []
  const activeCount    = activeListings.filter(l => l.status === 'active').length
  const salesHistory   = result.sales_history_5yr || []
  const attomMeta      = result.attom_meta        || {}
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

  // ── Stage 2 Piece B: bottom-up item-cost editing ──────────────────────────
  // Item costs are global: an edited cost applies everywhere the item shows
  // up across leaner/recommended/do_everything. shownItemIds mirrors the
  // floor+included-items membership used to build panelReq/panelOpt, but for
  // an arbitrary plan key rather than just the selected one.
  function shownItemIds(planKey) {
    const p = plans[planKey] || {}
    const ids = new Set((p.included_items || []).map(
      x => typeof x === 'string' ? x : x.component_id
    ))
    return new Set([...floorIds, ...ids])
  }

  function computeRepairCostForPlan(planKey, costsMap) {
    let sum = 0
    for (const cid of shownItemIds(planKey)) {
      const row = repair.find(r => r.component_id === cid)
      if (!row) continue
      sum += costsMap[cid] != null ? costsMap[cid] : itemCostMid(row)
    }
    return sum
  }

  // Edit one item's cost: update local display state, then PATCH repair_cost
  // for every plan that shows this item. Sequential on purpose — these PATCH
  // calls read-modify-write a single JSON column per session
  // (line_overrides_json); firing them in parallel risks a lost update where
  // one plan's write clobbers another's. Each plan is tried independently
  // (try/catch per iteration) so one failure doesn't block the rest; if any
  // plan fails, editError names exactly which tabs are now stale instead of
  // failing silently.
  async function commitItemCost(cid, rawVal) {
    const n = parseFloat(rawVal)
    const next = { ...customCosts }
    if (!isNaN(n) && n > 0) {
      next[cid] = n
    } else {
      delete next[cid]
    }
    setCustomCosts(next)

    const affectedPlans = planKeys.filter(pk => shownItemIds(pk).has(cid))
    setSaving(true)
    setEditError(null)
    const failed = []
    for (const pk of affectedPlans) {
      try {
        const amount = computeRepairCostForPlan(pk, next)
        const r = await updateOverride(sessionId, pk, 'repair_cost', amount)
        setResult(r)
      } catch (err) {
        failed.push(PLAN_LABELS[pk] || pk)
      }
    }
    if (failed.length > 0) {
      setEditError(
        `Cost update saved on some plans but failed on: ${failed.join(', ')}. ` +
        `Item totals may not match on ${failed.length > 1 ? 'those tabs' : 'that tab'} until you retry.`
      )
    }
    setSaving(false)
  }

  // Reset icon on the repair_cost line: clear every item override and revert
  // repair_cost to the calculated value on all three plans. Only plans that
  // currently carry a repair_cost override are PATCHed.
  async function resetAllItemCosts() {
    setCustomCosts({})
    setSaving(true)
    setEditError(null)
    const failed = []
    for (const pk of planKeys) {
      const li = (plans[pk]?.net_proceeds?.line_items || []).find(x => x.key === 'repair_cost')
      if (!li || li.override_amount == null) continue
      try {
        const r = await updateOverride(sessionId, pk, 'repair_cost', null)
        setResult(r)
      } catch (err) {
        failed.push(PLAN_LABELS[pk] || pk)
      }
    }
    if (failed.length > 0) {
      setEditError(
        `Reset saved on some plans but failed on: ${failed.join(', ')}. ` +
        `Item totals may not match on ${failed.length > 1 ? 'those tabs' : 'that tab'} until you retry.`
      )
    }
    setSaving(false)
  }

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
          <div><strong>Estimated market value (mid):</strong> {fmt(val.mid)}</div>
          <div><strong>Plan:</strong> {PLAN_LABELS[selectedPlan] || 'Custom'}</div>
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

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
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
              title="Copy this ID to resume the session later">
          session: {sessionId}
        </span>
      </div>

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
            Adjust the payoff amount on the plan card below if the figure isn't accurate.
          </p>
        </section>
      )}

      {/* ── 1. Plans (tabbed) ── */}
      <section style={{ ...sectionStyle, borderRadius: 12, border: '0.5px solid #e5e7eb' }}>
        <h3 style={h3}>Plans</h3>
        <div style={{ display: 'flex', gap: 6, marginBottom: 20, flexWrap: 'wrap' }}>
          {[...planKeys, 'custom'].map(key => (
            <button key={key}
              onClick={() => setSelectedPlan(key)}
              style={{
                padding: '6px 18px', borderRadius: 20,
                border: selectedPlan === key ? '1px solid #111827' : '1px solid #d1d5db',
                background: selectedPlan === key ? '#111827' : '#f9fafb',
                color: selectedPlan === key ? '#fff' : '#374151',
                fontWeight: selectedPlan === key ? 500 : 400,
                fontSize: 13, cursor: 'pointer',
              }}>
              {key === 'custom' ? 'Custom' : PLAN_LABELS[key]}
            </button>
          ))}
        </div>
        {selectedPlan === 'custom' ? (() => {
          const p = customPlan
          const doEverythingIds = new Set(plans.do_everything?.included_items || [])
          const reqRows = repair.filter(item => floorIds.has(item.component_id))
          const optRows = repair.filter(
            item => !floorIds.has(item.component_id) && doEverythingIds.has(item.component_id)
          )
          // Item 1: any required (floor) item unchecked on Custom? Frontend-only
          // detection, independent of backend lender_gate -- fires even when the
          // backend has no major/investor-cap item to report (e.g. Kingfisher).
          const anyRequiredUnchecked = [...floorIds].some(id => !customCheckedIds?.has(id))

          if (customLoading || !p) {
            return <p style={{ fontSize: 13, color: '#6b7280', padding: '20px 0' }}>Loading custom plan…</p>
          }
          if (customError && !p) {
            return <p style={{ fontSize: 13, color: 'red', padding: '20px 0' }}>Error: {customError}</p>
          }

          const isNeg = (p.net_proceeds?.net_proceeds ?? 0) < 0
          const checkedOptCount = optRows.filter(r => customCheckedIds?.has(r.component_id)).length

          return (
            <div style={{ opacity: customRecalculating ? 0.6 : 1, transition: 'opacity 0.15s' }}>
              {customRecalculating && (
                <div style={{ fontSize: 11, color: '#9ca3af', marginBottom: 6 }}>recalculating…</div>
              )}
              {customError && (
                <div style={{ fontSize: 12, color: '#c00', marginBottom: 8 }}>{customError}</div>
              )}
              <div style={{ display: 'flex', justifyContent: 'space-between',
                            alignItems: 'flex-start', flexWrap: 'wrap', gap: 12, marginBottom: 8 }}>
                <div>
                  <div style={{ fontWeight: 500, fontSize: 15, marginBottom: 3 }}>Custom</div>
                  <div style={{ fontSize: 12, color: '#6b7280' }}>
                    Build your own plan — required items are checked but can be unchecked.
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: 11, color: '#9ca3af', marginBottom: 2 }}>
                    Suggested listing price (estimate)
                  </div>
                  <div style={{ fontSize: 18, fontWeight: 500, marginBottom: 2 }}>
                    {fmt(p.adjusted_sale_price)}
                  </div>
                  {p.value_lift_capped > 0 && (
                    <div style={{ fontSize: 11, color: '#1a7f37' }}>
                      +{fmt(p.value_lift_capped)} est. value lift
                      {p.value_lift_cap_binding && (
                        <span style={{ marginLeft: 4, color: '#b45309' }}>
                          ⚑ capped<Tip id="valueLiftCapped" />
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </div>
              <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 16 }}>
                {reqRows.length} required + {checkedOptCount} of {optRows.length} optional checked
                {p.plan_roi_pct != null && (
                  <span style={{ marginLeft: 10, color: p.plan_roi_pct >= 0 ? '#1a7f37' : '#c00' }}>
                    ROI: {p.plan_roi_pct > 0 ? '+' : ''}{p.plan_roi_pct}%<Tip id="planROI" />
                  </span>
                )}
              </div>
              <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', alignItems: 'flex-start' }}>
                {/* Left: checkable item lists */}
                <div style={{ flex: '1 1 260px', minWidth: 200 }}>
                  {reqRows.length > 0 && (
                    <div style={{ marginBottom: 14 }}>
                      <div style={{ fontWeight: 500, fontSize: 12, color: '#7c2d12', marginBottom: 6,
                                    background: '#fef3c7', padding: '4px 8px', borderRadius: 4 }}>
                        Required to sell ({reqRows.length})
                      </div>
                      {reqRows.map((item, i) => (
                        <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                              fontSize: 12, padding: '4px 0',
                                              borderBottom: '1px solid #f3f4f6' }}>
                          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <input type="checkbox"
                              checked={customCheckedIds?.has(item.component_id) ?? false}
                              onChange={() => toggleCustomItem(item.component_id)} />
                            {item.display_name}
                            <span style={{ color: '#9ca3af' }}>
                              — {PATH_LABELS[item.better_value] || item.better_value}
                            </span>
                          </span>
                          <span style={{ whiteSpace: 'nowrap', marginLeft: 12 }}>
                            <CostCell
                              item={item}
                              customCosts={customCostOverrides}
                              editingCost={editingCost}
                              setEditingCost={setEditingCost}
                              onCostSave={commitCustomItemCost}
                            />
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                  {anyRequiredUnchecked && (
                    <div style={{ marginBottom: 14, padding: 12, border: '1px solid #dc2626',
                                  background: '#fef2f2', borderRadius: 6, fontSize: 12, color: '#991b1b' }}>
                      You've unchecked a required-to-sell item. Skipping required repairs can
                      make your home harder — or impossible — to sell to a typical buyer.
                    </div>
                  )}
                  {optRows.length > 0 && (
                    <div>
                      <div style={{ fontWeight: 500, fontSize: 12, color: '#065f46', marginBottom: 6,
                                    background: '#d1fae5', padding: '4px 8px', borderRadius: 4 }}>
                        Optional ({optRows.length})
                      </div>
                      {optRows.map((item, i) => (
                        <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                              fontSize: 12, padding: '4px 0',
                                              borderBottom: '1px solid #f3f4f6' }}>
                          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <input type="checkbox"
                              checked={customCheckedIds?.has(item.component_id) ?? false}
                              onChange={() => toggleCustomItem(item.component_id)} />
                            {item.display_name}
                            <span style={{ color: '#9ca3af' }}>
                              — {PATH_LABELS[item.better_value] || item.better_value}
                            </span>
                          </span>
                          <span style={{ whiteSpace: 'nowrap', marginLeft: 12 }}>
                            <CostCell
                              item={item}
                              customCosts={customCostOverrides}
                              editingCost={editingCost}
                              setEditingCost={setEditingCost}
                              onCostSave={commitCustomItemCost}
                            />
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                  {reqRows.length === 0 && optRows.length === 0 && (
                    <p style={{ fontSize: 12, color: '#9ca3af', marginTop: 0 }}>
                      No repair items detected.
                    </p>
                  )}

                  {/* Added items -- user-entered items not detected by the tool.
                      Full parity with Required/Optional: checkbox toggles whether the
                      cost counts in the net (unchecked = kept in the list, not counted),
                      cost is editable inline (same click-to-edit affordance as CostCell,
                      keyed by `added:${i}` in the shared editingCost state), and the ✕
                      control deletes the row entirely. */}
                  {customAddedItems.length > 0 && (
                    <div style={{ marginTop: 14, paddingTop: 10, borderTop: '1px solid #e5e7eb' }}>
                      <div style={{ fontWeight: 500, fontSize: 12, color: '#374151', marginBottom: 6,
                                    background: '#e5e7eb', padding: '4px 8px', borderRadius: 4 }}>
                        Added items ({customAddedItems.length})
                      </div>
                      {customAddedItems.map((it, i) => (
                        <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                              fontSize: 12, padding: '4px 0',
                                              borderBottom: '1px solid #f3f4f6',
                                              opacity: it.checked ? 1 : 0.55 }}>
                          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <input type="checkbox"
                              checked={it.checked}
                              onChange={() => toggleAddedItemChecked(i)} />
                            {it.label}
                          </span>
                          <span style={{ whiteSpace: 'nowrap', marginLeft: 12, display: 'flex', alignItems: 'center' }}>
                            {editingCost === `added:${i}` ? (
                              <input
                                type="number"
                                defaultValue={it.cost}
                                style={{ width: 90, fontSize: 12, padding: '2px 4px' }}
                                autoFocus
                                onBlur={e => { updateAddedItemCost(i, e.target.value); setEditingCost(null) }}
                                onKeyDown={e => { if (e.key === 'Enter') e.target.blur() }}
                              />
                            ) : (
                              <span
                                onClick={() => setEditingCost(`added:${i}`)}
                                title="Click to enter your own cost"
                                style={{ cursor: 'pointer', textDecorationLine: 'underline',
                                         textDecorationStyle: 'dotted', fontSize: 12 }}
                              >
                                {fmt(it.cost)}
                              </span>
                            )}
                            <button onClick={() => removeCustomAddedItem(i)}
                              style={{ marginLeft: 8, border: 'none', background: 'none',
                                       color: '#c00', cursor: 'pointer', fontSize: 12 }}>
                              ✕
                            </button>
                          </span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Add-your-own item -- cost-only, never affects value lift */}
                  <div style={{ marginTop: 14, paddingTop: 10, borderTop: '1px solid #e5e7eb' }}>
                    <div style={{ fontWeight: 500, fontSize: 12, color: '#374151', marginBottom: 6 }}>
                      Add an item the tool didn't detect
                    </div>
                    <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
                      <input placeholder="Description" value={newItemLabel}
                        onChange={e => setNewItemLabel(e.target.value)}
                        style={{ fontSize: 12, padding: '3px 6px', flex: 1, minWidth: 100 }} />
                      <input type="number" placeholder="Cost" value={newItemCost}
                        onChange={e => setNewItemCost(e.target.value)}
                        style={{ fontSize: 12, padding: '3px 6px', width: 80 }} />
                      <button onClick={addCustomItem}
                        style={{ fontSize: 12, padding: '3px 10px', cursor: 'pointer',
                                 border: '1px solid #ccc', borderRadius: 3, background: '#f9f9f9' }}>
                        Add
                      </button>
                    </div>
                  </div>
                </div>

                {/* Right: price-to-net chain (closing-cost lines read-only on Custom) */}
                <div style={{ flex: '0 1 260px', minWidth: 200, background: '#f9fafb',
                              borderRadius: 8, padding: '14px 16px', border: '0.5px solid #e5e7eb' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                                fontWeight: 500, fontSize: 12, marginBottom: 10, color: '#374151' }}>
                    <span>Price to net</span>
                    {saving && <span style={{ fontSize: 10, color: '#9ca3af', fontWeight: 400 }}>saving…</span>}
                  </div>
                  {editError && (
                    <div style={{ fontSize: 11, color: '#c00', marginBottom: 8 }}>{editError}</div>
                  )}
                  <div style={{ display: 'flex', justifyContent: 'space-between',
                                marginBottom: 10, fontSize: 13 }}>
                    <span>Listing price</span>
                    <span style={{ fontWeight: 500 }}>{fmt(p.adjusted_sale_price)}</span>
                  </div>
                  {(p.net_proceeds?.line_items || []).map((li, i) => (
                    <NetLineRow
                      key={li.key || i}
                      li={li}
                      planLevel="custom"
                      readOnly={PER_PLAN_KEYS.has(li.key)}
                      editingLine={editingLine}
                      setEditingLine={setEditingLine}
                      commission={commission}
                      setCommission={setCommission}
                      commissionRef={commissionRef}
                      payoffOpen={payoffOpen}
                      setPayoffOpen={setPayoffOpen}
                      payoffPrimary={payoffPrimary}
                      setPayoffPrimary={setPayoffPrimary}
                      payoffSecondary={payoffSecondary}
                      setPayoffSecondary={setPayoffSecondary}
                      payoffOther={payoffOther}
                      setPayoffOther={setPayoffOther}
                      saving={saving}
                      commitOverride={commitOverride}
                      commitGlobal={commitGlobal}
                      grossPrice={p.net_proceeds?.gross_sale_price}
                      resetAllItemCosts={resetAllItemCosts}
                    />
                  ))}
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 10,
                                paddingTop: 10, borderTop: '1px solid #d1d5db',
                                fontWeight: 500, fontSize: 13 }}>
                    <span>Est. net proceeds</span>
                    <span style={{ color: isNeg ? '#c00' : '#1a7f37' }}>{fmt(p.net_proceeds?.net_proceeds)}</span>
                  </div>
                </div>
              </div>

              {/* Custom's own lender-gate note -- backend already frames retail vs. investor pricing */}
              {p.lender_gate?.note && (
                <div style={{ marginTop: 16, padding: 14, border: '1px solid #f0c040',
                              background: '#fffbe6', borderRadius: 6 }}>
                  <div style={{ fontWeight: 500, fontSize: 13, marginBottom: 6, color: '#7a5c00' }}>
                    A required item is unchecked
                  </div>
                  <p style={{ fontSize: 12, color: '#4b5563', margin: '0 0 10px', lineHeight: 1.5 }}>
                    {p.lender_gate.note}
                  </p>
                  <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                    <div style={{ flex: 1, minWidth: 150 }}>
                      <div style={{ fontSize: 11, color: '#166534' }}>If repaired: retail price</div>
                      <div style={{ fontSize: 15, fontWeight: 500, color: '#15803d' }}>
                        {fmt(p.lender_gate.retail_price)}
                      </div>
                    </div>
                    <div style={{ flex: 1, minWidth: 150 }}>
                      <div style={{ fontSize: 11, color: '#6b7280' }}>As left: investor price</div>
                      <div style={{ fontSize: 15, fontWeight: 500, color: '#374151' }}>
                        ~{fmt(p.lender_gate.investor_price)}
                      </div>
                    </div>
                  </div>
                </div>
              )}
              {/* DOM omitted -- endpoint returns null for Custom, never fabricated */}
            </div>
          )
        })() : (() => {
          const p        = plans[selectedPlan] || {}
          const net      = p.net_proceeds || {}
          const planIds  = new Set((p.included_items || []).map(
            x => typeof x === 'string' ? x : x.component_id
          ))
          const panelReq = repair.filter(item => floorIds.has(item.component_id))
          const panelOpt = repair.filter(
            item => planIds.has(item.component_id) && !floorIds.has(item.component_id)
          )
          const isNeg = (net.net_proceeds ?? 0) < 0
          return (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between',
                            alignItems: 'flex-start', flexWrap: 'wrap', gap: 12, marginBottom: 8 }}>
                <div>
                  <div style={{ fontWeight: 500, fontSize: 15, marginBottom: 3 }}>
                    {PLAN_LABELS[selectedPlan]}
                  </div>
                  <div style={{ fontSize: 12, color: '#6b7280' }}>
                    {PLAN_DESCRIPTIONS[selectedPlan]}
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: 11, color: '#9ca3af', marginBottom: 2 }}>
                    Suggested listing price (estimate)
                  </div>
                  <div style={{ fontSize: 18, fontWeight: 500, marginBottom: 2 }}>
                    {fmt(p.adjusted_sale_price)}
                  </div>
                  {p.value_lift_capped > 0 && (
                    <div style={{ fontSize: 11, color: '#1a7f37' }}>
                      +{fmt(p.value_lift_capped)} est. value lift
                      {p.value_lift_cap_binding && (
                        <span style={{ marginLeft: 4, color: '#b45309' }}>
                          ⚑ capped<Tip id="valueLiftCapped" />
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </div>
              <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 16 }}>
                {p.dom?.estimated_dom} days est.
                {' · '}{panelReq.length} required + {panelOpt.length} optional items
                {p.plan_roi_pct != null && (
                  <span style={{ marginLeft: 10, color: p.plan_roi_pct >= 0 ? '#1a7f37' : '#c00' }}>
                    ROI: {p.plan_roi_pct > 0 ? '+' : ''}{p.plan_roi_pct}%<Tip id="planROI" />
                  </span>
                )}
              </div>
              <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', alignItems: 'flex-start' }}>
                {/* Left: repair list */}
                <div style={{ flex: '1 1 260px', minWidth: 200 }}>
                  {panelReq.length > 0 && (
                    <div style={{ marginBottom: 14 }}>
                      <div style={{ fontWeight: 500, fontSize: 12, color: '#7c2d12', marginBottom: 6,
                                    background: '#fef3c7', padding: '4px 8px', borderRadius: 4 }}>
                        Required to sell ({panelReq.length})
                      </div>
                      {panelReq.map((item, i) => (
                        <div key={i} style={{ display: 'flex', justifyContent: 'space-between',
                                              fontSize: 12, padding: '4px 0',
                                              borderBottom: '1px solid #f3f4f6' }}>
                          <span>
                            {item.display_name}
                            <span style={{ color: '#9ca3af', marginLeft: 4 }}>
                              — {PATH_LABELS[item.better_value] || item.better_value}
                            </span>
                          </span>
                          <span style={{ whiteSpace: 'nowrap', marginLeft: 12 }}>
                            <CostCell
                              item={item}
                              customCosts={customCosts}
                              editingCost={editingCost}
                              setEditingCost={setEditingCost}
                              onCostSave={commitItemCost}
                            />
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                  {panelOpt.length > 0 && (
                    <div>
                      <div style={{ fontWeight: 500, fontSize: 12, color: '#065f46', marginBottom: 6,
                                    background: '#d1fae5', padding: '4px 8px', borderRadius: 4 }}>
                        Optional — pays back at sale ({panelOpt.length})
                      </div>
                      {panelOpt.map((item, i) => (
                        <div key={i} style={{ display: 'flex', justifyContent: 'space-between',
                                              fontSize: 12, padding: '4px 0',
                                              borderBottom: '1px solid #f3f4f6' }}>
                          <span>
                            {item.display_name}
                            <span style={{ color: '#9ca3af', marginLeft: 4 }}>
                              — {PATH_LABELS[item.better_value] || item.better_value}
                            </span>
                          </span>
                          <span style={{ whiteSpace: 'nowrap', marginLeft: 12 }}>
                            <CostCell
                              item={item}
                              customCosts={customCosts}
                              editingCost={editingCost}
                              setEditingCost={setEditingCost}
                              onCostSave={commitItemCost}
                            />
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                  {panelReq.length === 0 && panelOpt.length === 0 && (
                    <p style={{ fontSize: 12, color: '#9ca3af', marginTop: 0 }}>
                      No repair items for this plan.
                    </p>
                  )}
                </div>
                {/* Right: price-to-net chain */}
                <div style={{ flex: '0 1 260px', minWidth: 200, background: '#f9fafb',
                              borderRadius: 8, padding: '14px 16px', border: '0.5px solid #e5e7eb' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                                fontWeight: 500, fontSize: 12, marginBottom: 10, color: '#374151' }}>
                    <span>Price to net</span>
                    {saving && <span style={{ fontSize: 10, color: '#9ca3af', fontWeight: 400 }}>saving…</span>}
                  </div>
                  {editError && (
                    <div style={{ fontSize: 11, color: '#c00', marginBottom: 8 }}>{editError}</div>
                  )}
                  <div style={{ display: 'flex', justifyContent: 'space-between',
                                marginBottom: 10, fontSize: 13 }}>
                    <span>Listing price</span>
                    <span style={{ fontWeight: 500 }}>{fmt(p.adjusted_sale_price)}</span>
                  </div>
                  {(net.line_items || []).map((li, i) => (
                    <NetLineRow
                      key={li.key || i}
                      li={li}
                      planLevel={selectedPlan}
                      editingLine={editingLine}
                      setEditingLine={setEditingLine}
                      commission={commission}
                      setCommission={setCommission}
                      commissionRef={commissionRef}
                      payoffOpen={payoffOpen}
                      setPayoffOpen={setPayoffOpen}
                      payoffPrimary={payoffPrimary}
                      setPayoffPrimary={setPayoffPrimary}
                      payoffSecondary={payoffSecondary}
                      setPayoffSecondary={setPayoffSecondary}
                      payoffOther={payoffOther}
                      setPayoffOther={setPayoffOther}
                      saving={saving}
                      commitOverride={commitOverride}
                      commitGlobal={commitGlobal}
                      grossPrice={net.gross_sale_price}
                      resetAllItemCosts={resetAllItemCosts}
                    />
                  ))}
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 10,
                                paddingTop: 10, borderTop: '1px solid #d1d5db',
                                fontWeight: 500, fontSize: 13 }}>
                    <span>Est. net proceeds</span>
                    <span style={{ color: isNeg ? '#c00' : '#1a7f37' }}>{fmt(net.net_proceeds)}</span>
                  </div>
                </div>
              </div>
            </div>
          )
        })()}
        <p style={caveatNote}>
          Days-on-market is based on historical averages and seasonality.
          A hot or slow market will shift this significantly.
        </p>
        <p style={caveatNote}>
          Time-to-sell is listing to closing only. It does not include time to complete
          major construction — your actual carrying costs will be higher while work is underway.
        </p>
      </section>

      {/* ── LenderGate ── */}
      {lenderGate && (
        <section style={sectionStyle}>
          <div style={{ fontWeight: 500, marginBottom: 8, color: '#374151', fontSize: 14 }}>
            Why these repairs matter for your buyer pool<Tip id="investorPath" />
          </div>
          <p style={{ margin: '0 0 10px', color: '#4b5563', lineHeight: 1.5, fontSize: 13 }}>
            Homes with active foundation moisture, roof leaks, or serious electrical issues
            usually can&apos;t be purchased with a conventional mortgage, FHA, or VA loan —
            because the lender requires the issue resolved before they&apos;ll fund the loan.
            That means most buyers can&apos;t purchase as-is, so the home tends to sell
            to a cash investor at a lower price.
            Addressing these before listing keeps your home open to all buyers.
          </p>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 10 }}>
            <div style={{ flex: 1, minWidth: 160, padding: '10px 14px',
                          background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 5 }}>
              <div style={{ fontSize: 11, color: '#166534', fontWeight: 500, marginBottom: 3 }}>
                If repaired: financed buyers, retail pricing
              </div>
              <div style={{ fontSize: 18, fontWeight: 500, color: '#15803d' }}>
                {fmt(lenderGate.retail_price)}
              </div>
              <div style={{ fontSize: 11, color: '#4b5563', marginTop: 3 }}>
                Full buyer pool, retail comp pricing
              </div>
            </div>
            <div style={{ flex: 1, minWidth: 160, padding: '10px 14px',
                          background: '#f9fafb', border: '1px solid #d1d5db', borderRadius: 5 }}>
              <div style={{ fontSize: 11, color: '#6b7280', fontWeight: 500, marginBottom: 3 }}>
                If left as-is: cash investors, ~75% of retail
              </div>
              <div style={{ fontSize: 18, fontWeight: 500, color: '#374151' }}>
                ~{fmt(lenderGate.investor_price)}
              </div>
              <div style={{ fontSize: 11, color: '#6b7280', marginTop: 3 }}>
                Approx. 75% of retail — investor pricing
              </div>
            </div>
          </div>
          <div style={{ fontSize: 12, color: '#6b7280' }}>
            Estimated gap: <strong style={{ color: '#374151' }}>{fmt(lenderGate.investor_gap)}</strong>
            {' '}between the two paths. Selling as-is to a cash buyer is a real option — for speed
            or when repair isn&apos;t feasible.
          </div>
          <div style={{ fontSize: 12, color: '#888', marginTop: 8 }}>
            See plan tabs above to compare net proceeds for each path.
          </div>
        </section>
      )}

      {/* ── 2. Estimated market value ── */}
      <section style={sectionStyle}>
        <h3 style={h3}>Estimated market value</h3>
        <div style={gridStyle}>
          <Stat label="Low"  value={fmt(val.low)} />
          <Stat label="Mid"  value={fmt(val.mid)} highlight />
          <Stat label="High" value={fmt(val.high)} />
          {val.avm_avg    && <Stat label="AVM avg"    value={fmt(val.avm_avg)} />}
          {val.confidence && <Stat label="Confidence" value={`${(val.confidence * 100).toFixed(0)}%`} />}
        </div>
        {val.note && <p style={noteStyle}>{val.note}</p>}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 10, flexWrap: 'wrap' }}>
          {attomMeta.comp_count > 0 ? (
            <span style={{ fontSize: 12, color: '#6b7280' }}>
              {attomMeta.comp_count} comp{attomMeta.comp_count !== 1 ? 's' : ''} from ATTOM
              {attomMeta.comp_radius_miles ? ` within ${attomMeta.comp_radius_miles} mi` : ''}
              {attomMeta.avm_as_of ? ` · AVM as of ${attomMeta.avm_as_of}` : ''}
            </span>
          ) : (
            <span style={{ fontSize: 12, color: '#9ca3af' }}>Market data from ATTOM</span>
          )}
          <button
            onClick={handleRefetchMarket}
            disabled={refetching}
            style={{
              fontSize: 11, padding: '2px 8px', borderRadius: 4,
              border: '1px solid #d1d5db', background: '#f9fafb',
              color: '#374151', cursor: refetching ? 'not-allowed' : 'pointer',
              opacity: refetching ? 0.6 : 1,
            }}
          >
            {refetching ? 'Refreshing…' : 'Refresh market data'}
          </button>
        </div>
      </section>

      {/* ── 3. Comparable sales ── */}
      {val.comp_detail?.length > 0 && (() => {
        const comps = val.comp_detail
        function colAvgC(arr, fn) {
          const vals = arr.map(fn).filter(v => v != null && !isNaN(v) && isFinite(v))
          return vals.length ? vals.reduce((s, v) => s + v, 0) / vals.length : null
        }
        const hasCol    = field => comps.some(c => c[field] != null && c[field] !== '' && c[field] !== false)
        const hasBeds   = hasCol('beds')
        const hasBaths  = hasCol('baths')
        const hasYrBlt  = hasCol('year_built')
        const hasDistMi = hasCol('distance_mi')
        const hasNote   = comps.some(c => c.note && c.note !== '')
        const avgSold   = colAvgC(comps, c => c.price)
        const avgPpsf   = colAvgC(comps, c => c.actual_ppsf)
        const avgSqft   = colAvgC(comps, c => c.sqft)
        const avgDist   = hasDistMi ? colAvgC(comps, c => c.distance_mi) : null
        const avgBeds   = hasBeds   ? colAvgC(comps, c => c.beds)  : null
        const avgBaths  = hasBaths  ? colAvgC(comps, c => c.baths) : null
        return (
          <section style={sectionStyle}>
            <h3 style={h3}>Comparable sales used in valuation</h3>
            <div style={gridStyle}>
              <Stat label="Comps"          value={comps.length} />
              <Stat label="Avg sold price" value={fmt(avgSold)} highlight />
              <Stat label="Avg cost/ft²"  value={avgPpsf ? `$${avgPpsf.toFixed(0)}` : '—'} />
              {avgSqft && <Stat label="Avg living ft²" value={Math.round(avgSqft).toLocaleString()} />}
            </div>
            <table style={tableStyle}>
              <thead><tr>
                <th style={th}>Address</th>
                {hasBeds   && <th style={{ ...th, textAlign: 'right' }}>Beds</th>}
                {hasBaths  && <th style={{ ...th, textAlign: 'right' }}>Baths</th>}
                <th style={{ ...th, textAlign: 'right' }}>Living ft²</th>
                {hasYrBlt  && <th style={{ ...th, textAlign: 'right' }}>Year Built</th>}
                <th style={{ ...th, textAlign: 'right' }}>Sold Price</th>
                <th style={{ ...th, textAlign: 'right' }}>Cost/ft²</th>
                <th style={th}>Sold Date</th>
                {hasDistMi && <th style={{ ...th, textAlign: 'right' }}>Dist (mi)</th>}
                <th style={{ ...th, textAlign: 'right' }}>Weight</th>
                {hasNote   && <th style={th}>Note</th>}
              </tr></thead>
              <tbody>
                {comps.map((c, i) => (
                  <tr key={i}>
                    <td style={td}>{c.address}</td>
                    {hasBeds   && <td style={{ ...td, textAlign: 'right' }}>{c.beds ?? '—'}</td>}
                    {hasBaths  && <td style={{ ...td, textAlign: 'right' }}>{c.baths ?? '—'}</td>}
                    <td style={{ ...td, textAlign: 'right' }}>{c.sqft ? Number(c.sqft).toLocaleString() : '—'}</td>
                    {hasYrBlt  && <td style={{ ...td, textAlign: 'right' }}>{c.year_built ?? '—'}</td>}
                    <td style={{ ...td, textAlign: 'right' }}>{fmt(c.price)}</td>
                    <td style={{ ...td, textAlign: 'right' }}>{c.actual_ppsf ? `$${c.actual_ppsf.toFixed(0)}` : '—'}</td>
                    <td style={td}>{c.sold_date || c.sold || '—'}</td>
                    {hasDistMi && <td style={{ ...td, textAlign: 'right' }}>{c.distance_mi != null ? c.distance_mi.toFixed(2) : '—'}</td>}
                    <td style={{ ...td, textAlign: 'right' }}>{c.weight != null ? `${(c.weight * 100).toFixed(1)}%` : '—'}</td>
                    {hasNote   && <td style={td}>{c.note || '—'}</td>}
                  </tr>
                ))}
                <tr style={{ background: '#f9fafb', fontWeight: 500, borderTop: '2px solid #e5e7eb' }}>
                  <td style={td}>Average</td>
                  {hasBeds   && <td style={{ ...td, textAlign: 'right' }}>{avgBeds  != null ? avgBeds.toFixed(1)  : '—'}</td>}
                  {hasBaths  && <td style={{ ...td, textAlign: 'right' }}>{avgBaths != null ? avgBaths.toFixed(1) : '—'}</td>}
                  <td style={{ ...td, textAlign: 'right' }}>{avgSqft ? Math.round(avgSqft).toLocaleString() : '—'}</td>
                  {hasYrBlt  && <td style={td}></td>}
                  <td style={{ ...td, textAlign: 'right' }}>{fmt(avgSold)}</td>
                  <td style={{ ...td, textAlign: 'right' }}>{avgPpsf ? `$${avgPpsf.toFixed(0)}` : '—'}</td>
                  <td style={td}></td>
                  {hasDistMi && <td style={{ ...td, textAlign: 'right' }}>{avgDist != null ? avgDist.toFixed(2) : '—'}</td>}
                  <td style={td}></td>
                  {hasNote   && <td style={td}></td>}
                </tr>
              </tbody>
            </table>
          </section>
        )
      })()}

      {/* ── 4. Active listings ── */}
      <section style={sectionStyle}>
        <h3 style={h3}>
          Active listings{activeCount > 0 ? ` — ${activeCount} active` : ''}
        </h3>
        {attomMeta.active_listings_basis && (
          <p style={{ ...noteStyle, marginTop: 0, marginBottom: 8, fontStyle: 'italic' }}>
            {attomMeta.active_listings_basis}
          </p>
        )}
        {(() => {
          const activeOnly = activeListings.filter(l => l.status === 'active')
          function colAvg(arr, fn) {
            const vals = arr.map(fn).filter(v => v != null && !isNaN(v) && isFinite(v))
            return vals.length ? vals.reduce((s, v) => s + v, 0) / vals.length : null
          }
          const alAvgPrice = colAvg(activeOnly, l => l.list_price || null)
          const alAvgPpsf  = colAvg(activeOnly, l => (l.sqft > 0 && l.list_price) ? l.list_price / l.sqft : null)
          const alAvgSqft  = colAvg(activeOnly, l => l.sqft || null)
          const alAvgBeds  = colAvg(activeOnly, l => l.beds  || null)
          const alAvgBaths = colAvg(activeOnly, l => l.baths || null)
          const alAvgDom   = colAvg(activeOnly, l => l.dom != null ? l.dom : null)
          return (
            <>
              {activeListings.length > 0 && (
                <div style={gridStyle}>
                  <Stat label="Active"         value={activeCount} />
                  <Stat label="Avg list price" value={fmt(alAvgPrice)} highlight />
                  <Stat label="Avg cost/ft²"  value={alAvgPpsf ? `$${alAvgPpsf.toFixed(0)}` : '—'} />
                  <Stat label="Avg living ft²" value={alAvgSqft ? Math.round(alAvgSqft).toLocaleString() : '—'} />
                  {alAvgDom != null && <Stat label="Avg DOM" value={Math.round(alAvgDom)} />}
                </div>
              )}
              {activeListings.length === 0 ? (
                <p style={noteStyle}>No active listings entered.</p>
              ) : (
                <table style={tableStyle}>
                  <thead><tr>
                    <th style={th}>Address</th>
                    <th style={{ ...th, textAlign: 'right' }}>Beds</th>
                    <th style={{ ...th, textAlign: 'right' }}>Baths</th>
                    <th style={{ ...th, textAlign: 'right' }}>Living ft²</th>
                    <th style={{ ...th, textAlign: 'right' }}>List Price</th>
                    <th style={{ ...th, textAlign: 'right' }}>Cost/ft²</th>
                    <th style={{ ...th, textAlign: 'right' }}>DOM</th>
                    <th style={th}>Status</th>
                  </tr></thead>
                  <tbody>
                    {activeListings.map((l, i) => {
                      const isPending = l.status === 'pending'
                      const ppsf = (l.sqft > 0 && l.list_price) ? Math.round(l.list_price / l.sqft) : null
                      return (
                        <tr key={i} style={{ opacity: isPending ? 0.75 : 1 }}>
                          <td style={td}>{l.address}</td>
                          <td style={{ ...td, textAlign: 'right' }}>{l.beds ?? '—'}</td>
                          <td style={{ ...td, textAlign: 'right' }}>{l.baths ?? '—'}</td>
                          <td style={{ ...td, textAlign: 'right' }}>{l.sqft?.toLocaleString() || '—'}</td>
                          <td style={{ ...td, textAlign: 'right' }}>{fmt(l.list_price)}</td>
                          <td style={{ ...td, textAlign: 'right' }}>{ppsf ? `$${ppsf}` : '—'}</td>
                          <td style={{ ...td, textAlign: 'right' }}>{l.dom ?? '—'}</td>
                          <td style={td}>
                            <span style={{
                              fontSize: 11, fontWeight: 500, padding: '2px 6px', borderRadius: 3,
                              background: isPending ? '#fef3c7' : '#d1fae5',
                              color:      isPending ? '#92400e' : '#065f46',
                            }}>
                              {isPending ? 'Pending' : 'Active'}
                            </span>
                          </td>
                        </tr>
                      )
                    })}
                    {activeOnly.length > 0 && (
                      <tr style={{ background: '#f9fafb', fontWeight: 500, borderTop: '2px solid #e5e7eb' }}>
                        <td style={td}>Avg (active)</td>
                        <td style={{ ...td, textAlign: 'right' }}>{alAvgBeds  ? alAvgBeds.toFixed(1)  : '—'}</td>
                        <td style={{ ...td, textAlign: 'right' }}>{alAvgBaths ? alAvgBaths.toFixed(1) : '—'}</td>
                        <td style={{ ...td, textAlign: 'right' }}>{alAvgSqft ? Math.round(alAvgSqft).toLocaleString() : '—'}</td>
                        <td style={{ ...td, textAlign: 'right' }}>{fmt(alAvgPrice)}</td>
                        <td style={{ ...td, textAlign: 'right' }}>{alAvgPpsf ? `$${alAvgPpsf.toFixed(0)}` : '—'}</td>
                        <td style={{ ...td, textAlign: 'right' }}>{alAvgDom != null ? Math.round(alAvgDom) : '—'}</td>
                        <td style={td}></td>
                      </tr>
                    )}
                  </tbody>
                </table>
              )}
            </>
          )
        })()}
      </section>

      {/* ── 5. Homes sold in July ── */}
      {salesHistory.length > 0 && (
        <section style={sectionStyle}>
          <h3 style={h3}>Homes sold in July</h3>
          <p style={{ ...noteStyle, marginTop: 0, marginBottom: 10,
                      borderLeft: '3px solid #b45309', paddingLeft: 8, color: '#92400e' }}>
            <strong>Context only — not used in valuation.</strong> Homes that sold in July
            (2022–2025) within 1 mile. Shows seasonal pricing patterns.
          </p>
          {(() => {
            const okCount   = salesHistory.filter(r => r.list_price_status === 'ok').length
            const hasNoData = salesHistory.some(r => r.list_price_status === 'no_data')
            function histSold(r) { return r.sold_price ?? r.price ?? null }
            function histDate(r) { return r.sold_date ?? r.sold ?? '—' }
            function histPpsf(r) {
              if (r.ppsf) return r.ppsf
              const sp = histSold(r); const sq = r.sqft
              return (sp && sq > 0) ? Math.round(sp / sq) : null
            }
            function colAvgH(arr, fn) {
              const vals = arr.map(fn).filter(v => v != null && !isNaN(v) && isFinite(v))
              return vals.length ? vals.reduce((s, v) => s + v, 0) / vals.length : null
            }
            const avgSoldH  = colAvgH(salesHistory, histSold)
            const avgPpsfH  = colAvgH(salesHistory, histPpsf)
            const avgSqftH  = colAvgH(salesHistory, r => r.sqft  || null)
            const avgBedsH  = colAvgH(salesHistory, r => r.beds  || null)
            const avgBathsH = colAvgH(salesHistory, r => r.baths || null)
            const lpRows    = salesHistory.filter(r => r.list_price_status === 'ok')
            const avgLpH    = colAvgH(lpRows, r => r.list_price || null)
            return (
              <>
                <table style={tableStyle}>
                  <thead><tr>
                    <th style={th}>Address</th>
                    <th style={{ ...th, textAlign: 'right' }}>Beds</th>
                    <th style={{ ...th, textAlign: 'right' }}>Baths</th>
                    <th style={{ ...th, textAlign: 'right' }}>Living ft²</th>
                    <th style={{ ...th, textAlign: 'right' }}>Year Built</th>
                    <th style={{ ...th, textAlign: 'right' }}>List Price</th>
                    <th style={{ ...th, textAlign: 'right' }}>Sold Price</th>
                    <th style={{ ...th, textAlign: 'right' }}>Cost/ft²</th>
                    <th style={th}>Sold Date</th>
                  </tr></thead>
                  <tbody>
                    {salesHistory.map((r, i) => {
                      const sp   = histSold(r)
                      const ppsf = histPpsf(r)
                      const lpOk = r.list_price_status === 'ok'
                      const lpNd = r.list_price_status === 'no_data'
                      return (
                        <tr key={i}>
                          <td style={td}>{r.address}</td>
                          <td style={{ ...td, textAlign: 'right' }}>{r.beds ?? '—'}</td>
                          <td style={{ ...td, textAlign: 'right' }}>{r.baths ?? '—'}</td>
                          <td style={{ ...td, textAlign: 'right' }}>{r.sqft ? Number(r.sqft).toLocaleString() : '—'}</td>
                          <td style={{ ...td, textAlign: 'right' }}>{r.year_built ?? '—'}</td>
                          <td style={{ ...td, textAlign: 'right' }}>
                            {lpOk ? fmt(r.list_price) : lpNd ? '—*' : '—'}
                          </td>
                          <td style={{ ...td, textAlign: 'right' }}>{fmt(sp)}</td>
                          <td style={{ ...td, textAlign: 'right' }}>{ppsf ? `$${ppsf}` : '—'}</td>
                          <td style={td}>{histDate(r)}</td>
                        </tr>
                      )
                    })}
                    <tr style={{ background: '#f9fafb', fontWeight: 500, borderTop: '2px solid #e5e7eb' }}>
                      <td style={td}>Average</td>
                      <td style={{ ...td, textAlign: 'right' }}>{avgBedsH  != null ? avgBedsH.toFixed(1)  : '—'}</td>
                      <td style={{ ...td, textAlign: 'right' }}>{avgBathsH != null ? avgBathsH.toFixed(1) : '—'}</td>
                      <td style={{ ...td, textAlign: 'right' }}>{avgSqftH ? Math.round(avgSqftH).toLocaleString() : '—'}</td>
                      <td style={td}></td>
                      <td style={{ ...td, textAlign: 'right' }}>{avgLpH ? fmt(avgLpH) : '—'}</td>
                      <td style={{ ...td, textAlign: 'right' }}>{fmt(avgSoldH)}</td>
                      <td style={{ ...td, textAlign: 'right' }}>{avgPpsfH ? `$${avgPpsfH.toFixed(0)}` : '—'}</td>
                      <td style={td}></td>
                    </tr>
                  </tbody>
                </table>
                {hasNoData && (
                  <p style={{ fontSize: 11, color: '#888', marginTop: 6 }}>
                    * List price unavailable for some sales; shown where records exist ({okCount} of {salesHistory.length}).
                  </p>
                )}
              </>
            )
          })()}
        </section>
      )}

      {/* ── Print footer ── */}
      <div className="print-footer" style={{ display: 'none' }}>
        <span>{result.address || 'Pre-Listing Decision Report'}</span>
        <span>Pre-Listing Decision Tool</span>
      </div>
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
const gridStyle     = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(90px, 1fr))', gap: 12, marginBottom: 10 }
const noteStyle     = { fontSize: 12, color: '#666', marginTop: 6, marginBottom: 0 }
const tableStyle    = { borderCollapse: 'collapse', width: '100%', fontSize: 13 }
const labelStyle    = { display: 'block', fontSize: 13, marginBottom: 10 }
const btnStyle      = { padding: '7px 18px', fontSize: 13, cursor: 'pointer', background: '#1a1a1a', color: '#fff', border: 'none', borderRadius: 3 }
const detailsLink   = { fontSize: 12, color: '#2563eb', cursor: 'pointer', textDecoration: 'underline' }
const th            = { textAlign: 'left', padding: '4px 8px', fontWeight: 600, borderBottom: '1px solid #e5e7eb', fontSize: 12, color: '#555' }
const td            = { padding: '4px 8px', borderBottom: '1px solid #f0f0f0', verticalAlign: 'middle', fontSize: 13 }
const caveatNote    = { fontSize: 11, color: '#9ca3af', marginTop: 4, marginBottom: 0 }

function planCardStyle(selected) {
  return {
    border: selected ? '2px solid #1a1a1a' : '1px solid #e5e7eb',
    borderRadius: 6, padding: '12px 16px', marginBottom: 10,
    cursor: 'pointer', background: selected ? '#f9fafb' : '#fff',
  }
}

function tabStyle(selected) {
  return {
    padding: '6px 14px', fontSize: 13, cursor: 'pointer',
    border: '1px solid #e5e7eb', borderRadius: 3, marginRight: 6,
    background: selected ? '#1a1a1a' : '#fff',
    color: selected ? '#fff' : '#374151',
    fontWeight: selected ? 600 : 400,
  }
}

function liveNetBand(delta, isCustom) {
  return {
    display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 4,
    marginTop: 12, padding: '8px 12px', borderRadius: 4,
    background: isCustom ? '#fefce8' : '#f0fdf4',
    border: isCustom ? '1px solid #fde047' : '1px solid #bbf7d0',
  }
}
