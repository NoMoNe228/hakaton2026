import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ask, fmtTime } from '../api.js'
import { ResultItem } from './Search.jsx'
import '../knowledge.css'

// Энциклопедия курса: все понятия из всех лекций, с определениями и переходом к моменту в видео
export default function Knowledge() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [params, setParams] = useSearchParams()
  const [filter, setFilter] = useState('')
  const opened = params.get('c') || ''

  useEffect(() => {
    api
      .knowledge()
      .then(setData)
      .catch((e) => setError(e.message))
  }, [])

  const shown = useMemo(() => {
    if (!data) return []
    const f = norm(filter)
    if (!f) return data.concepts
    return data.concepts.filter((c) => norm(c.name).includes(f) || norm(c.definition).includes(f))
  }, [data, filter])

  const letters = useMemo(() => [...new Set(shown.map((c) => c.letter))], [shown])

  const open = (name) => {
    const next = new URLSearchParams(params)
    name && name !== opened ? next.set('c', name) : next.delete('c')
    setParams(next, { replace: true })
  }

  // Открытое понятие из ссылки — прокрутить к нему
  useEffect(() => {
    if (!opened || !data) return
    const el = document.getElementById(anchor(opened))
    el?.scrollIntoView({ block: 'start', behavior: 'smooth' })
  }, [opened, data])

  return (
    <div className="page narrow kb">
      <div className="kb-head">
        <div>
          <h1>Энциклопедия курса</h1>
          <p className="muted">
            Понятия из всех лекций в одном месте: определение, в каких лекциях о нём говорят и с какой минуты.
            Собирается сама из конспектов.
          </p>
        </div>
        <Link to="/help" className="kb-help-link">
          Справка по сервису →
        </Link>
      </div>

      {error && <div className="alert">{error}</div>}
      {!data && !error && <div className="muted">Собираю понятия…</div>}

      {data && (
        <>
          <div className="kb-tools">
            <div className="searchbox compact">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <circle cx="11" cy="11" r="7" />
                <path d="M20 20l-3.5-3.5" />
              </svg>
              <input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Найти понятие"
                aria-label="Найти понятие"
              />
            </div>
            <span className="muted small">
              {plural(data.concepts.length, 'понятие', 'понятия', 'понятий')} из{' '}
              {plural(data.lectures, 'лекции', 'лекций', 'лекций')}
            </span>
          </div>

          {letters.length > 1 && (
            <nav className="kb-letters" aria-label="Алфавит">
              {letters.map((l) => (
                <a key={l} href={`#kb-${l}`}>
                  {l}
                </a>
              ))}
            </nav>
          )}

          {data.concepts.length === 0 && (
            <div className="empty">
              Понятий пока нет. Они появятся, когда у лекций будут готовы конспекты.
            </div>
          )}
          {data.concepts.length > 0 && shown.length === 0 && (
            <div className="empty">Такого понятия нет. Попробуйте поиск по всем лекциям — он ищет по смыслу.</div>
          )}

          {letters.map((l) => (
            <section key={l} id={`kb-${l}`} className="kb-letter">
              <h2>{l}</h2>
              {shown
                .filter((c) => c.letter === l)
                .map((c) => (
                  <Concept key={c.name} c={c} isOpen={c.name === opened} onToggle={() => open(c.name)} onOpen={open} />
                ))}
            </section>
          ))}
        </>
      )}
    </div>
  )
}

function Concept({ c, isOpen, onToggle, onOpen }) {
  return (
    <article id={anchor(c.name)} className={`kb-concept ${isOpen ? 'open' : ''}`}>
      <button className="kb-concept-head" onClick={onToggle} aria-expanded={isOpen}>
        <svg className="chevron" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M9 6l6 6-6 6" />
        </svg>
        <span className="kb-name">{c.name}</span>
        <span className="kb-def ellipsis">{c.definition}</span>
        <span className="kb-count muted small" title="В скольких лекциях встречается">
          {plural(c.lectures, 'лекция', 'лекции', 'лекций')}
        </span>
      </button>
      {isOpen && <ConceptBody c={c} onOpen={onOpen} />}
    </article>
  )
}

function ConceptBody({ c, onOpen }) {
  const [found, setFound] = useState(null)

  // Где ещё говорится о понятии — тот же поиск по смыслу, что и в строке поиска
  useEffect(() => {
    let alive = true
    api
      .search(c.name)
      .then((d) => alive && setFound(d.results.slice(0, 5)))
      .catch(() => alive && setFound([]))
    return () => {
      alive = false
    }
  }, [c.name])

  return (
    <div className="kb-body">
      <h3>Определения в лекциях</h3>
      <ul className="kb-mentions">
        {c.mentions.map((m) => (
          <li key={m.lecture_id}>
            <Link to={`/lecture/${m.lecture_id}?t=${Math.floor(m.start)}`} className="timecode" title="Смотреть с этого места">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M8 5v14l11-7z" />
              </svg>
              {fmtTime(m.start)}
            </Link>
            <div>
              <div className="kb-lecture">{m.lecture_title}</div>
              {m.definition && <div>{m.definition}</div>}
            </div>
          </li>
        ))}
      </ul>

      {c.related.length > 0 && (
        <>
          <h3>Связанные понятия</h3>
          <div className="examples left">
            {c.related.map((r) => (
              <button key={r} className="chip" onClick={() => onOpen(r)}>
                {r}
              </button>
            ))}
          </div>
        </>
      )}

      <h3>Где об этом говорят</h3>
      {!found && <div className="muted small">Ищу по всем лекциям…</div>}
      {found && found.length === 0 && <div className="muted small">Других мест не нашлось.</div>}
      {found && found.length > 0 && (
        <ol className="results">
          {found.map((r) => (
            <ResultItem key={`${r.lecture_id}-${r.start}`} r={r} />
          ))}
        </ol>
      )}

      <Explain name={c.name} />
    </div>
  )
}

// «Объяснить подробнее»: локальная модель отвечает по материалам курса, со ссылками на моменты
function Explain({ name }) {
  const [state, setState] = useState(null) // {text, sources, error, busy}
  const alive = useRef(true)
  useEffect(() => () => (alive.current = false), [])

  const run = async () => {
    setState({ text: '', sources: [], busy: true })
    const patch = (fn) => alive.current && setState((s) => fn(s))
    try {
      await ask({ question: `Объясни понятие «${name}» простыми словами по материалам лекций.` }, (ev) => {
        if (ev.sources) patch((s) => ({ ...s, sources: ev.sources }))
        if (ev.delta) patch((s) => ({ ...s, text: s.text + ev.delta }))
        if (ev.error) patch((s) => ({ ...s, error: ev.error }))
      })
    } catch (e) {
      patch((s) => ({ ...s, error: e.message }))
    } finally {
      patch((s) => ({ ...s, busy: false }))
    }
  }

  if (!state)
    return (
      <button className="btn kb-explain" onClick={run}>
        Объяснить подробнее
      </button>
    )
  const parts = state.text.split(/(\[\d+(?:\s*,\s*\d+)*\])/g)
  return (
    <div className="kb-answer">
      <h3>Объяснение по материалам курса</h3>
      {state.error && <div className="alert-text">{state.error}</div>}
      {!state.text && state.busy && !state.error && <div className="muted">Ищу в лекциях и пишу объяснение…</div>}
      <div className="answer">
        {parts.map((p, i) => {
          const m = p.match(/^\[(.+)\]$/)
          if (!m) return <span key={i}>{p}</span>
          return m[1].split(',').map((x) => {
            const n = parseInt(x, 10)
            const s = state.sources[n - 1]
            return s ? (
              <Link
                key={`${i}-${n}`}
                className="cite"
                to={`/lecture/${s.lecture_id}?t=${Math.floor(s.jump)}`}
                title={`${s.lecture_title}: ${s.text}`}
              >
                {n} · {fmtTime(s.jump)}
              </Link>
            ) : null
          })
        })}
      </div>
    </div>
  )
}

const norm = (s) => (s || '').toLowerCase().replace(/ё/g, 'е')
const anchor = (name) => `kb-c-${encodeURIComponent(name)}`

function plural(n, one, few, many) {
  const m10 = n % 10
  const m100 = n % 100
  const w = m10 === 1 && m100 !== 11 ? one : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? few : many
  return `${n} ${w}`
}
