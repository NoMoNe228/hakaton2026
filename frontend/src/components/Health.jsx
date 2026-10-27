import { useEffect, useState } from 'react'
import { api } from '../api.js'

// Значок состояния: загружены ли модели, работает ли локальная языковая модель
export default function Health() {
  const [h, setH] = useState(null)
  const [err, setErr] = useState(false)

  useEffect(() => {
    let timer
    const load = () =>
      api
        .health()
        .then((d) => {
          setH(d)
          setErr(false)
          timer = setTimeout(load, d.search_ready && d.llm_ready ? 30000 : 3000)
        })
        .catch(() => {
          setErr(true)
          timer = setTimeout(load, 3000)
        })
    load()
    return () => clearTimeout(timer)
  }, [])

  if (err) return <div className="health bad">Сервер недоступен</div>
  if (!h) return <div className="health">…</div>
  if (h.search_error)
    return (
      <div className="health bad" title={h.search_error}>
        Модели поиска не загрузились
      </div>
    )
  const ok = h.search_ready && h.llm_ready
  const title = [
    `Вычисления: ${h.device === 'cuda' ? 'видеокарта' : 'процессор'}`,
    `Поиск: ${h.search_ready ? 'готов' : h.search_error || 'модели загружаются'}`,
    `Языковая модель ${h.llm}: ${h.llm_ready ? 'готова' : 'не запущена'}`,
  ].join('\n')
  return (
    <div className={`health ${ok ? 'ok' : 'warn'}`} title={title}>
      <span className="dot" />
      {!h.search_ready ? 'Загружаю модели…' : !h.llm_ready ? 'Без конспектов' : 'Офлайн · всё локально'}
    </div>
  )
}
