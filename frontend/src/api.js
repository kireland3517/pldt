const BASE = import.meta.env.VITE_API_URL || ''

async function json(res) {
  const text = await res.text()
  try { return JSON.parse(text) }
  catch { throw new Error(`Non-JSON response (${res.status}): ${text.slice(0, 200)}`) }
}

export async function createSession(address, propertyKey) {
  const res = await fetch(`${BASE}/session`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ address, property_key: propertyKey }),
  })
  if (!res.ok) throw new Error((await json(res)).detail || res.statusText)
  return json(res)
}

export async function tagPhoto(sessionId, file) {
  const fd = new FormData()
  fd.append('file', file)
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
  const res = await fetch(`${BASE}/session/${sessionId}/capture`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, ...payload }),
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
