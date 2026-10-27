import { useEffect, useState } from 'react'
import './LangSwitch.css'

const KEY = 'sut.lang'
const NAMES = { ru: 'RU', en: 'EN', de: 'DE', fr: 'FR', es: 'ES', it: 'IT', uk: 'UK', zh: 'ZH', ja: 'JA' }
const code = (l) => NAMES[l] || (l || '').toUpperCase()

function saved() {
  try {
    return localStorage.getItem(KEY)
  } catch {
    return null
  }
}

// Язык расшифровки: выбор запоминается (например, «всегда по-русски»).
// Если у лекции такого языка нет или перевод ещё не готов — показываем оригинал.
export function useTranscriptLang(lec) {
  const [pref, setPref] = useState(saved)
  const tr = lec?.translation
  useEffect(() => {
    const on = (e) => e.key === KEY && setPref(e.newValue)
    window.addEventListener('storage', on)
    return () => window.removeEventListener('storage', on)
  }, [])
  const choose = (l) => {
    setPref(l)
    try {
      localStorage.setItem(KEY, l)
    } catch {}
  }
  if (!tr) return [null, choose]
  const lang = pref === tr.tr && tr.ready ? tr.tr : tr.orig
  return [lang, choose]
}

// Перевод лежит в первой фразе предложения, у остальных его фраз text_tr пустой —
// склеиваем их в одну запись от начала первой фразы до конца последней.
function merged(segments) {
  const out = []
  for (const s of segments) {
    if (s.text_tr === '' && out.length) out[out.length - 1] = { ...out[out.length - 1], end: s.end }
    else out.push({ ...s, text: s.text_tr || s.text })
  }
  return out
}

// Фразы и оглавление на выбранном языке. Заголовки модель пишет по-русски,
// их перевод на второй язык лекции лежит в outline_alt.
export function localize(lec, segments, lang) {
  const tr = lec?.translation
  if (!tr || !lang) return { segments, outline: lec?.outline }
  const shown = lang === tr.tr ? merged(segments) : segments
  let outline = lec.outline
  const alt = lec.outline_alt
  if (alt && lang === alt.lang && outline?.length === alt.sections?.length) {
    outline = outline.map((sec, i) => ({
      ...sec,
      title: alt.sections[i].title || sec.title,
      children: sec.children.map((c, j) => ({ ...c, title: alt.sections[i].children?.[j] || c.title })),
    }))
  }
  return { segments: shown, outline }
}

// Переключатель «оригинал / перевод». Пока перевод готовится — так и пишем, текст остаётся оригинальным.
export default function LangSwitch({ lec, lang, onChange, onRetry }) {
  const tr = lec?.translation
  if (!tr || !tr.total) return null
  const pct = tr.total ? Math.round((100 * tr.done) / tr.total) : 0
  return (
    <div className="lang-switch" role="group" aria-label="Язык расшифровки">
      <button className={lang === tr.orig ? 'on' : ''} onClick={() => onChange(tr.orig)} title="Оригинал: текст, как его произнёс лектор">
        {code(tr.orig)}
      </button>
      {tr.ready ? (
        <button className={lang === tr.tr ? 'on' : ''} onClick={() => onChange(tr.tr)} title="Перевод локальной моделью">
          {code(tr.tr)} <span className="lang-note">· перевод</span>
        </button>
      ) : tr.error ? (
        <button className="pending" onClick={onRetry} title={tr.error}>
          {code(tr.tr)} <span className="lang-note">· ошибка, повторить</span>
        </button>
      ) : (
        <button
          className="pending"
          disabled
          title={tr.active ? 'Локальная модель переводит расшифровку' : 'Перевод начнётся, когда освободится видеокарта'}
        >
          {code(tr.tr)} <span className="lang-note">· {tr.active ? `перевожу ${pct}%` : 'перевод в очереди'}</span>
        </button>
      )}
    </div>
  )
}
