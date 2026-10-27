// Обращения к серверу
async function req(url, opts = {}) {
  const r = await fetch(url, opts)
  if (!r.ok) {
    let msg = r.statusText
    try {
      msg = (await r.json()).detail || msg
    } catch {}
    throw new Error(msg)
  }
  return r.json()
}

const json = (method, body) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  health: () => req('/api/health'),
  knowledge: () => req('/api/knowledge'),
  lectures: () => req('/api/lectures'),
  lecture: (id) => req(`/api/lectures/${id}`),
  segments: (id) => req(`/api/lectures/${id}/segments`),
  addUrl: (url, title = '') => req('/api/lectures/url', json('POST', { url, title })),
  rename: (id, title) => req(`/api/lectures/${id}`, json('PATCH', { title })),
  remove: (id) => req(`/api/lectures/${id}`, { method: 'DELETE' }),
  retry: (id) => req(`/api/lectures/${id}/retry`, { method: 'POST' }),
  resummarize: (id) => req(`/api/lectures/${id}/summarize`, { method: 'POST' }),
  translate: (id) => req(`/api/lectures/${id}/translate`, { method: 'POST' }),
  search: (q, lectureId) => {
    const p = new URLSearchParams({ q })
    if (lectureId) p.set('lecture_id', lectureId)
    return req(`/api/search?${p}`)
  },
}

// Загрузка файла с полосой прогресса (fetch не умеет отдавать ход отправки)
export function uploadFile(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const fd = new FormData()
    fd.append('file', file)
    xhr.open('POST', '/api/lectures/upload')
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total)
    xhr.onload = () => {
      let data = {}
      try {
        data = JSON.parse(xhr.responseText)
      } catch {}
      xhr.status < 300 ? resolve(data) : reject(new Error(data.detail || 'Не удалось загрузить файл'))
    }
    xhr.onerror = () => reject(new Error('Сервер недоступен'))
    xhr.send(fd)
  })
}

// Вопрос-ответ: ответ приходит построчно (источники, затем текст по кусочкам)
export async function ask({ question, lectureId, history }, onEvent) {
  const r = await fetch('/api/ask', json('POST', { question, lecture_id: lectureId || null, history }))
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'Ошибка сервера')
  const reader = r.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    let i
    while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i).trim()
      buf = buf.slice(i + 1)
      if (line) onEvent(JSON.parse(line))
    }
  }
}

export function fmtTime(sec) {
  sec = Math.max(0, Math.floor(sec || 0))
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = sec % 60
  const mm = String(m).padStart(2, '0')
  const ss = String(s).padStart(2, '0')
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`
}

export const STATUS = {
  queued: 'В очереди',
  downloading: 'Скачиваю видео',
  extracting: 'Извлекаю звук',
  waiting: 'Скачано, ждёт очереди',
  transcribing: 'Распознаю речь',
  indexing: 'Строю поисковый индекс',
  indexed: 'Конспект в очереди',
  summarizing: 'Пишу конспект',
  ready: 'Готово',
  error: 'Ошибка',
}

export const isSearchable = (s) => s === 'indexed' || s === 'summarizing' || s === 'ready'
export const isBusy = (s) => s !== 'ready' && s !== 'error'

const LANG_TO = { ru: 'на русский', en: 'на английский' }
// Перевод готовой лекции идёт отдельно и после неё; null — переводить нечего или уже готово
export function translationNote(tr) {
  if (!tr || !tr.total || tr.ready) return null
  if (tr.error) return { text: 'перевод не удался', kind: 'error' }
  const pct = Math.round((100 * tr.done) / tr.total)
  if (tr.active) return { text: `перевожу ${LANG_TO[tr.tr] || ''} ${pct}%`.replace('  ', ' '), kind: 'active', pct }
  return { text: tr.done ? `перевод в очереди (готово ${pct}%)` : 'перевод в очереди', kind: 'queued', pct }
}
export const translationPending = (l) => l.status === 'ready' && !!translationNote(l.translation) && !l.translation?.error
