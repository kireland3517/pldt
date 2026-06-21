import React, { useState } from 'react'
import { createSession } from '../api'

export default function AddressStep({ onDone }) {
  const [address, setAddress] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function submit(e) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const session = await createSession(address)
      onDone(session.session_id)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <div style={orientStyle}>
        <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>
          See what your home could net — and what's worth doing before you list.
        </h2>
        <p style={{ fontSize: 14, color: '#555', margin: 0 }}>
          Answer a few questions about your home and upload some photos.
          We'll show you three scenarios with estimated costs and net proceeds.
          About 15 minutes.
        </p>
      </div>

      <form onSubmit={submit}>
        <label style={labelStyle}>
          Your home's address
          <input
            style={inputStyle}
            value={address}
            onChange={e => setAddress(e.target.value)}
            placeholder="130 Kingfisher Dr"
            required
          />
        </label>

        {error && <p style={{ color: 'red', marginTop: 8 }}>{error}</p>}

        <button style={btnStyle} type="submit" disabled={loading}>
          {loading ? 'Getting started...' : 'Get started'}
        </button>
      </form>
    </div>
  )
}

const orientStyle = { marginBottom: 24, paddingBottom: 20, borderBottom: '1px solid #eee' }
const labelStyle  = { display: 'block', marginBottom: 16, fontWeight: 500 }
const inputStyle  = { display: 'block', width: '100%', marginTop: 4, padding: '6px 8px', fontSize: 14, boxSizing: 'border-box' }
const btnStyle    = { marginTop: 8, padding: '8px 20px', fontSize: 14, cursor: 'pointer' }