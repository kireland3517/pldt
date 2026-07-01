const BASE = import.meta.env.VITE_API_URL || ''

async function json(res) {
  const text = await res.text()
  try { return JSON.parse(text) }
  catch { throw new Error(`Non-JSON response (${res.status}): ${text.slice(0, 200)}`) }
}

export async function getSession(sessionId) {
  const res = await fetch(`${BASE}/session/${sessionId}`)
  if (!res.ok) throw new Error(res.statusText)
  return json(res)
}

export async function createSession(address) {
  const res = await fetch(`${BASE}/session`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ address }),
  })
  if (!res.ok) throw new Error((await json(res)).detail || res.statusText)
  return json(res)
}

export async function tagPhoto(sessionId, file, room_zone = 'other') {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('room_zone', room_zone)
  const res = await fetch(`${BASE}/session/${sessionId}/photo`, { method: 'POST', body: fd })
  if (!res.ok) throw new Error((await json(res)).detail || res.statusText)
  return json(res)
}

export async function getQuestions(sessionId) {
  const res = await fetch(`${BASE}/session/${sessionId}/questions`)
  if (!res.ok) throw new Error(res.statusText)
  return json(res)
}

export async function submitCapture(sessionId, payload) {
  // payload: { photoTagsForCapture, sellerConfirmedTags, absencePresenceAnswers,
  //            presence_answers, condition_answers, has_inspection_report }
  const body = {
    session_id:           sessionId,
    has_inspection_report: payload.has_inspection_report || false,
    photo_tags:           payload.photoTagsForCapture || [],
    seller_confirmed_tags: payload.sellerConfirmedTags || [],
    presence_answers:     [
      ...(payload.absencePresenceAnswers || []),
      ...(payload.presence_answers || []),
    ],
    condition_answers:    payload.condition_answers || [],
    seller_inputs:        payload.seller_inputs || {},
  }
  const res = await fetch(`${BASE}/session/${sessionId}/capture`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error((await json(res)).detail || res.statusText)
  return json(res)
}

export async function getCompute(sessionId, refresh = false) {
  const url = `${BASE}/session/${sessionId}/compute${refresh ? '?refresh=true' : ''}`
  const res = await fetch(url)
  if (!res.ok) throw new Error((await json(res)).detail || res.statusText)
  return json(res)
}

export async function refetchMarketData(sessionId) {
  const res = await fetch(`${BASE}/session/${sessionId}/refetch-market-data`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error((await json(res)).detail || res.statusText)
  return json(res)
}

export async function updateInputs(sessionId, patch) {
  const res = await fetch(`${BASE}/session/${sessionId}/inputs`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
  if (!res.ok) throw new Error((await json(res)).detail || res.statusText)
  return json(res)
}

export async function updateOverride(sessionId, planLevel, lineKey, amount) {
  // Stage 2 Step 2: set or clear a single per-plan line override.
  // amount = null clears the override (reverts to calculated_amount).
  const res = await fetch(`${BASE}/session/${sessionId}/overrides`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ plan_level: planLevel, line_key: lineKey, amount }),
  })
  if (!res.ok) throw new Error((await json(res)).detail || res.statusText)
  return json(res)
}

export async function listSessions(limit = 20) {
  const res = await fetch(`${BASE}/session?limit=${limit}`)
  if (!res.ok) throw new Error(res.statusText)
  return json(res)
}

export async function downloadPdf(sessionId, { planKey, customItems, customCosts, liveNet }) {
  const body = {
    plan_key:     planKey,
    custom_items: customItems ? [...customItems] : null,
    custom_costs: (customCosts && Object.keys(customCosts).length > 0) ? customCosts : null,
    live_net:     liveNet,
  }
  const res = await fetch(`${BASE}/session/${sessionId}/pdf`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(body),
  })
  if (!res.ok) {
    const msg = await res.text()
    throw new Error(`PDF generation failed (${res.status}): ${msg.slice(0, 200)}`)
  }
  const blob = await res.blob()
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = `pldt-report-${sessionId.slice(0, 8)}.pdf`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export async function downloadLargePdf(sessionId, { planKey, customItems, customCosts, liveNet }) {
  const body = {
    plan_key:     planKey,
    custom_items: customItems ? [...customItems] : null,
    custom_costs: (customCosts && Object.keys(customCosts).length > 0) ? customCosts : null,
    live_net:     liveNet,
  }
  const res = await fetch(`${BASE}/session/${sessionId}/pdf/large`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(body),
  })
  if (!res.ok) {
    const msg = await res.text()
    throw new Error(`Large-print PDF failed (${res.status}): ${msg.slice(0, 200)}`)
  }
  const blob = await res.blob()
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = `pldt-report-large-${sessionId.slice(0, 8)}.pdf`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
