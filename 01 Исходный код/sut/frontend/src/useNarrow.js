import { useEffect, useState } from 'react'

// Узкий экран (телефон): длинные подсказки в полях ввода там обрезаются, поэтому показываем короткие
const QUERY = '(max-width: 640px)'

export function useNarrow() {
  const [narrow, setNarrow] = useState(() => window.matchMedia(QUERY).matches)
  useEffect(() => {
    const m = window.matchMedia(QUERY)
    const onChange = (e) => setNarrow(e.matches)
    m.addEventListener('change', onChange)
    return () => m.removeEventListener('change', onChange)
  }, [])
  return narrow
}
