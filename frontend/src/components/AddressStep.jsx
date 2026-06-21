import React, { useState } from 'react'
import { createSession } from '../api'

export default function AddressStep({ onDone }) {
  const [address, setAddress] = useState('')
  const [propertyKey, setPropertyKey] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function submit(e) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const session = await createSession(address, propertyKey)
      onDone(session.session_id)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={submit}>
      <h2 style={{ fontSize: 16, marginBottom: 16 }}>Property Address</h2>

      <label style={labelStyle}>
        Street address
        <input
          style={inputStyle}
          value={address}
          onChange={e => setAddress(e.target.value)}
          placeholder="130 Kingfisher Dr"
          required
        />
      </label>

      <label style={labelStyle}>
        Property key (seed file name, e.g. <code>130_kingfisher</code>)
        <input
          style={inputStyle}
          value={propertyKey}
          onChange={e => setPropertyKey(e.target.value)}
          placeholder="130_kingfisher"
          required
        />
        <small style={{ color: '#666' }}>
          Must match a seed file in <code>backend/seed/property_inputs_*.json</code>
        </small>
      </label>

      {error && <p style={{ color: 'red', marginTop: 8 }}>{error}</p>}

      <button style={btnStyle} type="submit" disabled={loading}>
        {loading ? 'Creating session...' : 'Start session'}
      </button>
    </form>
  )
}

const labelStyle = { display: 'block', marginBottom: 16, fontWeight: 500 }
const inputStyle  = { display: 'block', width: '100%', marginTop: 4, padding: '6px 8px', fontSize: 14, boxSizing: 'border-box' }
const btnStyle    = { marginTop: 8, padding: '8px 20px', fontSize: 14, cursor: 'pointer' }
