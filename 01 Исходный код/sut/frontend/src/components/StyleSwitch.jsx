import { useState } from 'react'

// Переключатель стиля оформления: обычный (по умолчанию) или «пикми».
// Выбор хранится в браузере и ставится атрибутом data-style на <html>.
const KEY = 'sut-style'

export function savedStyle() {
  try {
    return localStorage.getItem(KEY) === 'pickme' ? 'pickme' : 'default'
  } catch {
    return 'default'
  }
}

export function applyStyle(style) {
  if (style === 'pickme') document.documentElement.dataset.style = 'pickme'
  else delete document.documentElement.dataset.style
}

export default function StyleSwitch() {
  const [style, setStyle] = useState(savedStyle)
  const on = style === 'pickme'

  const toggle = () => {
    const next = on ? 'default' : 'pickme'
    setStyle(next)
    applyStyle(next)
    try {
      localStorage.setItem(KEY, next)
    } catch {
      // браузер не даёт сохранять — стиль просто не запомнится
    }
  }

  return (
    <button
      type="button"
      className={`style-switch${on ? ' on' : ''}`}
      aria-pressed={on}
      onClick={toggle}
      title={on ? 'Вернуть обычный стиль' : 'Включить стиль «пикми»'}
    >
      <svg viewBox="0 0 24 24">
        <path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z" />
      </svg>
      <span>Пикми</span>
    </button>
  )
}
