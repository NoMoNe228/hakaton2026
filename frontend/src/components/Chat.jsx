import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ask, fmtTime } from '../api.js'

const SUGGEST = ['О чём эта лекция?', 'Какие примеры приводит лектор?', 'Объясни главный термин простыми словами']

// «Вопрос-ответ» по лекции: ответ строится только по найденным фрагментам, со ссылками на время
export default function Chat({ lectureId, onSeek }) {
  const [msgs, setMsgs] = useState([])
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [scope, setScope] = useState('lecture')
  const end = useRef()

  const send = async (text) => {
    text = (text ?? q).trim()
    if (!text || busy) return
    setQ('')
    setBusy(true)
    const history = msgs.map(({ role, content }) => ({ role, content }))
    setMsgs((m) => [...m, { role: 'user', content: text }, { role: 'assistant', content: '', sources: [] }])
    const patchLast = (fn) => setMsgs((m) => [...m.slice(0, -1), fn(m[m.length - 1])])
    try {
      await ask({ question: text, lectureId: scope === 'lecture' ? lectureId : null, history }, (ev) => {
        if (ev.sources) patchLast((x) => ({ ...x, sources: ev.sources }))
        if (ev.delta) patchLast((x) => ({ ...x, content: x.content + ev.delta }))
        if (ev.error) patchLast((x) => ({ ...x, error: ev.error }))
        end.current?.scrollIntoView({ block: 'nearest' })
      })
    } catch (e) {
      patchLast((x) => ({ ...x, error: e.message }))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="chat">
      <div className="chat-scope">
        <span className="muted small">Искать ответ:</span>
        <button className={scope === 'lecture' ? 'chip on' : 'chip'} onClick={() => setScope('lecture')}>
          в этой лекции
        </button>
        <button className={scope === 'all' ? 'chip on' : 'chip'} onClick={() => setScope('all')}>
          во всём курсе
        </button>
      </div>
      <div className="chat-log">
        {msgs.length === 0 && (
          <div className="examples">
            {SUGGEST.map((s) => (
              <button key={s} className="chip" onClick={() => send(s)}>
                {s}
              </button>
            ))}
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            {m.role === 'assistant' ? (
              <Answer m={m} lectureId={lectureId} onSeek={onSeek} pending={busy && i === msgs.length - 1} />
            ) : (
              m.content
            )}
          </div>
        ))}
        <div ref={end} />
      </div>
      <form
        className="chat-input"
        onSubmit={(e) => {
          e.preventDefault()
          send()
        }}
      >
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Спросите о содержании лекции" />
        <button type="submit" disabled={busy || !q.trim()}>
          {busy ? '…' : 'Спросить'}
        </button>
      </form>
    </div>
  )
}

function SourceLink({ s, n, lectureId, onSeek }) {
  const label = `${n} · ${fmtTime(s.jump)}`
  if (s.lecture_id === lectureId)
    return (
      <button className="cite" onClick={() => onSeek(s.jump)} title={s.text}>
        {label}
      </button>
    )
  return (
    <Link className="cite" to={`/lecture/${s.lecture_id}?t=${Math.floor(s.jump)}`} title={`${s.lecture_title}: ${s.text}`}>
      {label}
    </Link>
  )
}

function Answer({ m, lectureId, onSeek, pending }) {
  // Ссылки вида [1] превращаем в кнопки перехода к фрагменту
  const parts = m.content.split(/(\[\d+(?:\s*,\s*\d+)*\])/g)
  return (
    <>
      {m.error && <div className="alert-text">{m.error}</div>}
      {!m.content && pending && !m.error && <span className="muted">Ищу в лекции и думаю…</span>}
      <div className="answer">
        {parts.map((p, i) => {
          const mm = p.match(/^\[(.+)\]$/)
          if (!mm) return <span key={i}>{p}</span>
          return mm[1].split(',').map((x) => {
            const n = parseInt(x, 10)
            const s = m.sources[n - 1]
            return s ? <SourceLink key={`${i}-${n}`} s={s} n={n} lectureId={lectureId} onSeek={onSeek} /> : null
          })
        })}
      </div>
      {!pending && m.sources?.length > 0 && /\[\d/.test(m.content) && (
        <div className="sources muted small">
          Источники:{' '}
          {m.sources.map((s, i) => (
            <SourceLink key={i} s={s} n={i + 1} lectureId={lectureId} onSeek={onSeek} />
          ))}
        </div>
      )}
    </>
  )
}
