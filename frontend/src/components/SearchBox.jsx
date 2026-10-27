import { useEffect, useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useNarrow } from '../useNarrow.js'

// Поиск по всем лекциям курса
export default function SearchBox({ compact = false, autoFocus = false }) {
  const [params] = useSearchParams()
  const loc = useLocation()
  const nav = useNavigate()
  const narrow = useNarrow()
  const [q, setQ] = useState(loc.pathname === '/search' ? params.get('q') || '' : '')

  useEffect(() => {
    if (loc.pathname === '/search') setQ(params.get('q') || '')
  }, [loc.pathname, params])

  // На главной большая строка поиска уже есть — маленькую в шапке прячем
  if (compact && loc.pathname === '/') return <div className="topbar-spacer" />

  const submit = (e) => {
    e.preventDefault()
    if (q.trim()) nav(`/search?q=${encodeURIComponent(q.trim())}`)
  }

  return (
    <form className={compact ? 'searchbox compact' : 'searchbox'} onSubmit={submit} role="search">
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="11" cy="11" r="7" />
        <path d="M20 20l-3.5-3.5" />
      </svg>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={compact ? 'Поиск по всем лекциям' : narrow ? 'Что найти по смыслу?' : 'Что найти? Например: «объяснение теоремы Пифагора»'}
        autoFocus={autoFocus}
        aria-label="Поисковый запрос"
      />
      <button type="submit" disabled={!q.trim()}>
        Найти
      </button>
    </form>
  )
}
