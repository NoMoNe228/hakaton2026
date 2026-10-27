import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api, fmtTime, isBusy, isSearchable, STATUS } from '../api.js'
import Player from '../components/Player.jsx'
import Transcript from '../components/Transcript.jsx'
import LangSwitch, { localize, useTranscriptLang } from '../components/LangSwitch.jsx'
import Chat from '../components/Chat.jsx'
import { ResultItem } from './Search.jsx'

const TABS = [
  ['outline', 'Оглавление'],
  ['summary', 'Конспект'],
  ['terms', 'Термины'],
  ['chat', 'Вопрос-ответ'],
]

export default function Lecture() {
  const { id } = useParams()
  const [params] = useSearchParams()
  const startAt = Number(params.get('t')) || 0
  const [lec, setLec] = useState(null)
  const [error, setError] = useState('')
  const [segments, setSegments] = useState([])
  const [time, setTime] = useState(0)
  const [tab, setTab] = useState('outline')
  const player = useRef()
  const [lang, setLang] = useTranscriptLang(lec)

  const load = useCallback(
    () =>
      api
        .lecture(id)
        .then(setLec)
        .catch((e) => setError(e.message)),
    [id],
  )

  useEffect(() => {
    setLec(null)
    setSegments([])
    load()
  }, [load])

  // Пока лекция обрабатывается — обновляем состояние
  useEffect(() => {
    if (!lec || !isBusy(lec.status)) return
    const t = setTimeout(load, 2000)
    return () => clearTimeout(t)
  }, [lec, load])

  const hasText = lec && ['indexing', 'indexed', 'summarizing', 'ready'].includes(lec.status)
  useEffect(() => {
    if (hasText && segments.length === 0) api.segments(id).then(setSegments)
  }, [hasText, id, segments.length])

  // Перевод готовится в фоне — следим за ним и, как будет готов, берём фразы заново (уже с переводом)
  const trReady = !!lec?.translation?.ready
  const trWaiting = lec?.status === 'ready' && lec.translation && !trReady && !lec.translation.error
  useEffect(() => {
    if (!trWaiting) return
    const t = setTimeout(load, 5000)
    return () => clearTimeout(t)
  }, [trWaiting, lec, load])
  useEffect(() => {
    if (trReady) api.segments(id).then(setSegments)
  }, [trReady, id])
  const shown = useMemo(() => localize(lec, segments, lang), [lec, segments, lang])
  const tracks = useMemo(() => {
    const tr = lec?.translation
    if (!segments.length) return []
    const base = `/api/lectures/${id}/subtitles.vtt`
    const list = [{ src: base, lang: tr?.orig || 'ru', label: 'Оригинал' }]
    if (tr?.ready) list.push({ src: `${base}?lang=tr`, lang: tr.tr, label: 'Перевод' })
    return list
  }, [id, segments.length, lec?.translation?.ready, lec?.translation?.orig, lec?.translation?.tr])

  // Переход по ссылке с таймкодом, когда страница уже открыта
  useEffect(() => {
    if (startAt) player.current?.seek(startAt)
  }, [startAt])

  const seek = useCallback((t) => player.current?.seek(t), [])

  if (error) return <div className="page"><div className="alert">{error}</div></div>
  if (!lec) return <div className="page muted">Загрузка…</div>

  return (
    <div className="page lecture">
      <div className="crumbs">
        <Link to="/">← Все лекции</Link>
      </div>
      <Title lec={lec} onChange={load} />

      {isBusy(lec.status) && !['indexed', 'summarizing'].includes(lec.status) && (
        <div className="processing">
          <div>
            <b>{STATUS[lec.status]}</b> · {Math.round(lec.progress)}%
            {lec.status === 'waiting' && <span className="muted"> — распознавание начнётся, как только видеокарта закончит предыдущую лекцию</span>}
            {lec.status === 'transcribing' && <span className="muted"> — поиск и текст появятся, как только речь будет распознана</span>}
          </div>
          <div className="bar">
            <div style={{ width: `${lec.progress}%` }} />
          </div>
        </div>
      )}
      {lec.status === 'error' && (
        <div className="alert">
          {lec.error}{' '}
          <button className="link" onClick={() => api.retry(id).then(load)}>
            Повторить
          </button>
        </div>
      )}

      <div className="lecture-grid">
        <div className="col-main">
          {lec.video_file ? (
            <Player
              ref={player}
              src={`/api/lectures/${id}/video`}
              tracks={tracks}
              track={lang && lang === lec.translation?.tr ? 1 : 0}
              startAt={startAt}
              onTime={setTime}
            />
          ) : (
            <div className="player placeholder">Видео загружается…</div>
          )}

          <div className="tabs" role="tablist">
            {TABS.map(([k, label]) => (
              <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>
                {label}
              </button>
            ))}
          </div>
          <div className="tab-body">
            {tab === 'chat' ? (
              isSearchable(lec.status) ? (
                <Chat lectureId={id} onSeek={seek} />
              ) : (
                <div className="muted">Чат станет доступен, когда лекция будет расшифрована.</div>
              )
            ) : (
              <SummaryTabs tab={tab} lec={lec} time={time} onSeek={seek} onRegen={() => api.resummarize(id).then(load)} />
            )}
          </div>
        </div>

        <aside className="col-side">
          <LectureSearch id={id} enabled={isSearchable(lec.status)} onSeek={seek} />
          {segments.length ? (
            <Transcript
              segments={shown.segments}
              outline={shown.outline}
              time={time}
              onSeek={seek}
              langSwitch={<LangSwitch lec={lec} lang={lang} onChange={setLang} onRetry={() => api.translate(id).then(load)} />}
            />
          ) : (
            <div className="muted small pad">Расшифровка появится после распознавания речи.</div>
          )}
        </aside>
      </div>
    </div>
  )
}

function Title({ lec, onChange }) {
  const [edit, setEdit] = useState(false)
  const [v, setV] = useState(lec.title)
  if (edit)
    return (
      <form
        className="title-edit"
        onSubmit={async (e) => {
          e.preventDefault()
          await api.rename(lec.id, v)
          setEdit(false)
          onChange()
        }}
      >
        <input value={v} onChange={(e) => setV(e.target.value)} autoFocus />
        <button type="submit">Сохранить</button>
        <button type="button" className="link" onClick={() => setEdit(false)}>
          Отмена
        </button>
      </form>
    )
  return (
    <h1 className="lecture-title">
      {lec.title}{' '}
      <button className="link small" onClick={() => setEdit(true)} title="Переименовать">
        ✎
      </button>
      <span className="meta muted">
        {lec.duration ? fmtTime(lec.duration) : ''}
        {lec.language ? ` · ${lec.language === 'ru' ? 'русский' : lec.language === 'en' ? 'английский' : lec.language}` : ''}
        {lec.source_url ? (
          <>
            {' · '}
            <a href={lec.source_url} target="_blank" rel="noreferrer">
              источник
            </a>
          </>
        ) : null}
      </span>
    </h1>
  )
}

function LectureSearch({ id, enabled, onSeek }) {
  const [q, setQ] = useState('')
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const run = async (e) => {
    e.preventDefault()
    if (!q.trim()) return
    setBusy(true)
    setErr('')
    try {
      setRes((await api.search(q.trim(), id)).results)
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="lecture-search">
      <form className="searchbox compact" onSubmit={run}>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={enabled ? 'Найти в этой лекции по смыслу' : 'Поиск появится после расшифровки'}
          disabled={!enabled}
        />
        <button type="submit" disabled={!enabled || busy || !q.trim()}>
          {busy ? '…' : 'Найти'}
        </button>
      </form>
      {err && <div className="alert-text small">{err}</div>}
      {res && (
        <div className="lecture-results">
          <div className="row-between">
            <span className="muted small">{res.length ? `Найдено: ${res.length}` : 'Ничего близкого не нашлось'}</span>
            <button className="link small" onClick={() => setRes(null)}>
              Закрыть ✕
            </button>
          </div>
          <ol className="results">
            {res.map((r) => (
              <ResultItem key={r.start} r={r} onJump={onSeek} showLecture={false} />
            ))}
          </ol>
        </div>
      )}
    </div>
  )
}

function SummaryTabs({ tab, lec, time, onSeek, onRegen }) {
  if (!lec.summary) {
    if (lec.summary_error)
      return (
        <div className="alert">
          {lec.summary_error}{' '}
          <button className="link" onClick={onRegen}>
            Попробовать снова
          </button>
        </div>
      )
    if (lec.status === 'indexed')
      return <div className="muted">Конспект в очереди: сначала распознаются другие скачанные лекции. Искать по лекции уже можно.</div>
    if (lec.status === 'summarizing')
      return (
        <div className="muted">
          Локальная модель пишет конспект и оглавление… {Math.round(lec.progress)}%
          <div className="bar">
            <div style={{ width: `${lec.progress}%` }} />
          </div>
        </div>
      )
    return <div className="muted">Конспект появится после расшифровки лекции.</div>
  }

  if (tab === 'summary')
    return (
      <div className="summary">
        <p>{lec.summary.text}</p>
        {lec.summary.key_points?.length > 0 && (
          <>
            <h3>Главное</h3>
            <ul>
              {lec.summary.key_points.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ul>
          </>
        )}
        <button className="link small" onClick={onRegen}>
          Составить заново
        </button>
      </div>
    )

  if (tab === 'terms')
    return lec.terms?.length ? (
      <dl className="terms">
        {lec.terms.map((t) => (
          <div key={t.term} className="term">
            <dt>
              <button className="timecode plain" onClick={() => onSeek(t.start)}>
                {fmtTime(t.start)}
              </button>{' '}
              {t.term}
            </dt>
            <dd>{t.definition}</dd>
          </div>
        ))}
      </dl>
    ) : (
      <div className="muted">Ключевые термины не выделены.</div>
    )

  // Оглавление: разделы и подразделы; текущий подсвечен
  return (
    <ol className="outline">
      {lec.outline?.map((sec, i) => (
        <li key={i} className={time >= sec.start && time < sec.end ? 'current' : ''}>
          <button className="outline-row section" onClick={() => onSeek(sec.start)}>
            <span className="timecode">{fmtTime(sec.start)}</span>
            <span>{sec.title}</span>
          </button>
          {sec.children.length === 1 ? (
            sec.children[0].points?.length > 0 && (
              <ul className="points">
                {sec.children[0].points.map((p, k) => (
                  <li key={k}>{p}</li>
                ))}
              </ul>
            )
          ) : (
          <ol>
            {sec.children.map((c, j) => (
              <li key={j} className={time >= c.start && time < c.end ? 'current' : ''}>
                <button className="outline-row" onClick={() => onSeek(c.start)}>
                  <span className="timecode">{fmtTime(c.start)}</span>
                  <span>{c.title}</span>
                </button>
                {c.points?.length > 0 && (
                  <ul className="points">
                    {c.points.map((p, k) => (
                      <li key={k}>{p}</li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ol>
          )}
        </li>
      ))}
    </ol>
  )
}
