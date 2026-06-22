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

export async function updateInputs(sessionId, patch) {
  const res = await fetch(`${BASE}/session/${sessionId}/inputs`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
  if (!res.ok) throw new Error((await json(res)).detail || res.statusText)
  return json(res)
}
