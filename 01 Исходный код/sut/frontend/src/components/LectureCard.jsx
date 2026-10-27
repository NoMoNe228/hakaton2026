import { Link } from 'react-router-dom'
import { api, fmtTime, isBusy, STATUS, translationNote } from '../api.js'

export default function LectureCard({ lecture: l, onChange }) {
  const busy = isBusy(l.status)
  const tr = l.status === 'ready' ? translationNote(l.translation) : null

  const remove = async (e) => {
    e.preventDefault()
    if (!confirm(`Удалить лекцию «${l.title}»? Видео и расшифровка будут удалены.`)) return
    await api.remove(l.id)
    onChange()
  }
  const retry = async (e) => {
    e.preventDefault()
    await api.retry(l.id)
    onChange()
  }

  return (
    <Link to={`/lecture/${l.id}`} className={`card lecture-card ${l.status}`}>
      <div className="thumb">
        {!['queued', 'downloading'].includes(l.status) && (
          <img
            src={`/api/lectures/${l.id}/thumb.jpg`}
            alt=""
            loading="lazy"
            onError={(e) => (e.currentTarget.style.display = 'none')}
          />
        )}
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M8 5v14l11-7z" />
        </svg>
        {l.duration ? <span className="duration">{fmtTime(l.duration)}</span> : null}
        {l.language && <span className="lang">{l.language.toUpperCase()}</span>}
      </div>
      <div className="card-body">
        <div className="title" title={l.title}>
          {l.title}
        </div>
        <div className={`status ${l.status}`}>
          {STATUS[l.status] || l.status}
          {busy && !['queued', 'waiting'].includes(l.status) && ` · ${Math.round(l.progress)}%`}
          {l.status === 'ready' && tr && <span className={`tr-note ${tr.kind}`}> · {tr.text}</span>}
        </div>
        {tr?.kind === 'active' && (
          <div className="bar thin">
            <div style={{ width: `${tr.pct}%` }} />
          </div>
        )}
        {busy && (
          <div className="bar">
            <div style={{ width: `${l.progress}%` }} />
          </div>
        )}
        {l.status === 'error' && (
          <div className="alert-text small" title={l.error}>
            {l.error}
          </div>
        )}
        <div className="card-actions">
          {l.status === 'error' && (
            <button className="link" onClick={retry}>
              Повторить
            </button>
          )}
          <button className="link danger" onClick={remove}>
            Удалить
          </button>
        </div>
      </div>
    </Link>
  )
}
