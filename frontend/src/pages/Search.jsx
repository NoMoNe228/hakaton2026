import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, fmtTime } from '../api.js'
import Snippet from '../components/Snippet.jsx'

// Результаты поиска по всем лекциям
export default function SearchPage() {
  const [params] = useSearchParams()
  const q = params.get('q') || ''
  const [state, setState] = useState({ loading: true })

  useEffect(() => {
    if (!q) return
    let alive = true
    setState({ loading: true })
    const t0 = performance.now()
    api
      .search(q)
      .then((d) => alive && setState({ results: d.results, respelled: d.respelled, ms: Math.round(performance.now() - t0) }))
      .catch((e) => alive && setState({ error: e.message }))
    return () => {
      alive = false
    }
  }, [q])

  return (
    <div className="page narrow">
      <h1 className="search-title">
        «{q}»
      </h1>
      {state.loading && <div className="muted">Ищу по смыслу…</div>}
      {state.error && <div className="alert">{state.error}</div>}
      {state.results && (
        <div className="muted small">
          {state.results.length
            ? `Найдено фрагментов: ${state.results.length} · ${(state.ms / 1000).toFixed(2)} с`
            : 'Ничего близкого по смыслу не нашлось. Попробуйте сформулировать иначе.'}
          {state.respelled && <> · искал как «{state.respelled}»</>}
        </div>
      )}
      <ol className="results">
        {state.results?.map((r, i) => (
          <ResultItem key={`${r.lecture_id}-${r.start}`} r={r} rank={i} />
        ))}
      </ol>
    </div>
  )
}

export function ResultItem({ r, onJump, showLecture = true }) {
  const to = `/lecture/${r.lecture_id}?t=${Math.floor(r.jump)}`
  const time = (
    <span className="timecode">
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M8 5v14l11-7z" />
      </svg>
      {fmtTime(r.jump)}
    </span>
  )
  return (
    <li className="result">
      <div className="result-head">
        {onJump ? (
          <button className="plain" onClick={() => onJump(r.jump)} title="Перейти к этому моменту">
            {time}
          </button>
        ) : (
          <Link to={to} title="Смотреть с этого момента">
            {time}
          </Link>
        )}
        {showLecture && (
          <Link to={to} className="result-lecture ellipsis">
            {r.lecture_title}
          </Link>
        )}
        <Relevance score={r.score} />
      </div>
      <p className="result-text">
        <Snippet text={r.text} spans={r.highlights} />
      </p>
    </li>
  )
}

function Relevance({ score }) {
  const label = score > 0.6 ? 'точное совпадение' : score > 0.25 ? 'близко по смыслу' : 'возможно связано'
  return (
    <span className="relevance" title={`Оценка соответствия: ${Math.round(score * 100)}%`}>
      <span className="meter">
        <span style={{ width: `${Math.max(8, Math.round(score * 100))}%` }} />
      </span>
      {label}
    </span>
  )
}
