// Текст фрагмента с подсвеченными словами запроса
export default function Snippet({ text, spans = [] }) {
  if (!spans.length) return <span>{text}</span>
  const out = []
  let pos = 0
  spans.forEach(([a, b], i) => {
    if (a > pos) out.push(text.slice(pos, a))
    out.push(<mark key={i}>{text.slice(a, b)}</mark>)
    pos = b
  })
  out.push(text.slice(pos))
  return <span>{out}</span>
}
