import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import SearchBox from '../components/SearchBox.jsx'
import Uploader from '../components/Uploader.jsx'
import LectureCard from '../components/LectureCard.jsx'
import { isBusy, translationPending } from '../api.js'

const EXAMPLES = ['основная идея лекции', 'пример из практики', 'определение и формула', 'what is gradient descent']

export default function Home() {
  const [list, setList] = useState(null)
  const [error, setError] = useState('')
  const nav = useNavigate()

  const load = useCallback(() => api.lectures().then(setList).catch((e) => setError(e.message)), [])

  useEffect(() => {
    load()
  }, [load])

  // Пока что-то обрабатывается — обновляем список каждые 2 секунды
  useEffect(() => {
    if (!list?.some((l) => isBusy(l.status) || translationPending(l))) return
    const t = setTimeout(load, 2000)
    return () => clearTimeout(t)
  }, [list, load])

  return (
    <div className="page home">
      <section className="hero">
        <h1>Найдите нужный момент в лекции по смыслу</h1>
        <p className="muted">
          Загрузите видео — сервис распознает речь, построит оглавление и конспект, а поиск найдёт фрагмент, даже если
          в лекции сказано другими словами. Русский и английский. Всё работает на этом компьютере.
        </p>
        <SearchBox autoFocus />
        <div className="examples">
          {EXAMPLES.map((e) => (
            <button key={e} className="chip" onClick={() => nav(`/search?q=${encodeURIComponent(e)}`)}>
              {e}
            </button>
          ))}
        </div>
      </section>

      <Uploader onAdded={load} />

      <section>
        <div className="section-head">
          <h2>Лекции</h2>
          {list && <span className="muted">{list.length}</span>}
        </div>
        {error && <div className="alert">{error}</div>}
        {list && list.length === 0 && (
          <div className="empty">Пока нет ни одной лекции. Загрузите видео или вставьте ссылку на YouTube выше.</div>
        )}
        <div className="grid">
          {list?.map((l) => (
            <LectureCard key={l.id} lecture={l} onChange={load} />
          ))}
        </div>
      </section>
    </div>
  )
}
