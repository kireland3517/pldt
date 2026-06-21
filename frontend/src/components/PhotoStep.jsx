import React, { useState, useRef } from 'react'
import { tagPhoto } from '../api'

export default function PhotoStep({ sessionId, onDone }) {
  const [photos, setPhotos] = useState([])   // [{file, url, status, result, error}]
  const [allTags, setAllTags] = useState([])
  const inputRef = useRef()

  async function handleFiles(e) {
    const files = Array.from(e.target.files)
    if (!files.length) return

    const newEntries = files.map(f => ({
      file: f,
      url: URL.createObjectURL(f),
      status: 'pending',
      result: null,
      error: null,
    }))

    setPhotos(prev => {
      const updated = [...prev, ...newEntries]
      // tag each new file
      newEntries.forEach((entry, i) => {
        const idx = prev.length + i
        tagOne(entry.file, idx, updated.length)
      })
      return updated
    })
  }

  async function tagOne(file, idx, _total) {
    setPhotos(prev =>
      prev.map((p, i) => i === idx ? { ...p, status: 'tagging' } : p)
    )
    try {
      const result = await tagPhoto(sessionId, file)
      setPhotos(prev =>
        prev.map((p, i) => i === idx ? { ...p, status: 'done', result } : p)
      )
      setAllTags(prev => [...prev, ...result.tags])
    } catch (err) {
      setPhotos(prev =>
        prev.map((p, i) => i === idx ? { ...p, status: 'error', error: err.message } : p)
      )
    }
  }

  const allDone = photos.length > 0 && photos.every(p => p.status === 'done' || p.status === 'error')

  return (
    <div>
      <h2 style={{ fontSize: 16, marginBottom: 8 }}>Upload Photos</h2>
      <p style={{ fontSize: 13, color: '#555', marginBottom: 16 }}>
        Upload interior and exterior photos. Each photo is tagged by AI against the
        component library — blind to this property's known condition.
      </p>

      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        multiple
        style={{ display: 'none' }}
        onChange={handleFiles}
      />
      <button style={btnStyle} onClick={() => inputRef.current.click()}>
        Add photos
      </button>

      {photos.length > 0 && (
        <div style={{ marginTop: 20 }}>
          {photos.map((p, i) => (
            <div key={i} style={cardStyle}>
              <img src={p.url} alt={p.file.name} style={thumbStyle} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 500, fontSize: 13, marginBottom: 4, wordBreak: 'break-all' }}>
                  {p.file.name}
                </div>

                {p.status === 'pending' && <span style={badge('gray')}>Queued</span>}
                {p.status === 'tagging' && <span style={badge('blue')}>Tagging...</span>}
                {p.status === 'error'   && <span style={{ color: 'red', fontSize: 12 }}>Error: {p.error}</span>}

                {p.status === 'done' && p.result && (
                  <div>
                    <span style={badge('green')}>{p.result.tags.length} component{p.result.tags.length !== 1 ? 's' : ''} detected</span>
                    {p.result.dropped_invalid_ids?.length > 0 && (
                      <span style={{ fontSize: 11, color: '#999', marginLeft: 8 }}>
                        dropped: {p.result.dropped_invalid_ids.join(', ')}
                      </span>
                    )}
                    <table style={tableStyle}>
                      <thead>
                        <tr>
                          <th style={th}>ID</th>
                          <th style={th}>Present</th>
                          <th style={th}>Condition</th>
                          <th style={th}>Severity</th>
                          <th style={th}>Conf</th>
                          <th style={th}>Evidence</th>
                        </tr>
                      </thead>
                      <tbody>
                        {p.result.tags.map((t, j) => (
                          <tr key={j}>
                            <td style={td}><code>{t.component_id}</code></td>
                            <td style={td}>{t.present ? 'yes' : 'no'}</td>
                            <td style={td}>{t.condition}</td>
                            <td style={td}>{t.severity}</td>
                            <td style={td}>{(t.confidence * 100).toFixed(0)}%</td>
                            <td style={{ ...td, fontSize: 11, color: '#555' }}>{t.evidence}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {photos.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <p style={{ fontSize: 13, color: '#555' }}>
            {allTags.length} total tags across {photos.length} photo{photos.length !== 1 ? 's' : ''}.
            {!allDone && ' Waiting for tagging to complete...'}
          </p>
          <button
            style={{ ...btnStyle, marginTop: 8 }}
            onClick={() => onDone(allTags)}
            disabled={!allDone}
          >
            Continue to questionnaire
          </button>
        </div>
      )}

      {photos.length === 0 && (
        <p style={{ marginTop: 16, fontSize: 13, color: '#888' }}>
          No photos added yet. You can also skip photos and answer all questions manually.
        </p>
      )}

      {photos.length === 0 && (
        <button style={{ ...btnStyle, marginTop: 8, background: '#eee' }} onClick={() => onDone([])}>
          Skip photos, answer all questions
        </button>
      )}
    </div>
  )
}

const btnStyle   = { padding: '8px 20px', fontSize: 14, cursor: 'pointer' }
const cardStyle  = { display: 'flex', gap: 12, marginBottom: 16, padding: 12, border: '1px solid #ddd', borderRadius: 4 }
const thumbStyle = { width: 80, height: 80, objectFit: 'cover', borderRadius: 2, flexShrink: 0 }
const tableStyle = { marginTop: 8, borderCollapse: 'collapse', width: '100%', fontSize: 12 }
const th = { textAlign: 'left', padding: '2px 6px', borderBottom: '1px solid #ccc', fontWeight: 600 }
const td = { padding: '2px 6px', borderBottom: '1px solid #eee', verticalAlign: 'top' }
const badge = (color) => ({
  display: 'inline-block', fontSize: 11, padding: '1px 6px', borderRadius: 10,
  background: color === 'green' ? '#d4edda' : color === 'blue' ? '#cce5ff' : '#eee',
  color: color === 'green' ? '#155724' : color === 'blue' ? '#004085' : '#555',
  marginBottom: 6,
})
