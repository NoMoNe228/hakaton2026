import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fmtTime } from '../api.js'

// Номер фразы, которая звучит в момент t (двоичный поиск)
export function activeIndex(segments, t) {
  let lo = 0
  let hi = segments.length - 1
  let ans = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (segments[mid].start <= t + 0.05) {
      ans = mid
      lo = mid + 1
    } else hi = mid - 1
  }
  return ans
}

// Заголовки из оглавления: раздел, а если в нём несколько подразделов — и они
function headings(outline) {
  const out = []
  for (const sec of outline || []) {
    out.push({ level: 1, title: sec.title, start: sec.start })
    if (sec.children?.length > 1) {
      sec.children.forEach((c, j) => {
        // Первый подраздел начинается вместе с разделом — второй заголовок подряд не нужен
        if (j === 0 && Math.abs(c.start - sec.start) < 1) return
        out.push({ level: 2, title: c.title, start: c.start })
      })
    }
  }
  return out.sort((a, b) => a.start - b.start)
}

// Склеивает фразы в абзацы: ~40 с и конец предложения, но не длиннее ~70 с
function paragraphs(items) {
  const out = []
  let cur = []
  for (const it of items) {
    cur.push(it)
    const len = it.s.end - cur[0].s.start
    if ((len >= 40 && /[.!?…]$/.test(it.s.text)) || len >= 70) {
      out.push(cur)
      cur = []
    }
  }
  if (cur.length) out.push(cur)
  return out
}

function buildPlan(segments, outline) {
  const heads = headings(outline)
  const groups = heads.length ? heads.map((h) => ({ head: h, items: [] })) : [{ head: null, items: [] }]
  let g = 0
  segments.forEach((s, i) => {
    while (g + 1 < groups.length && s.start >= groups[g + 1].head.start - 0.5) g++
    groups[g].items.push({ s, i })
  })
  return groups.filter((x) => x.items.length).map((x) => ({ head: x.head, pars: paragraphs(x.items) }))
}

// Раздел верхнего уровня, к которому относится каждая группа (подразделы сворачиваются вместе с ним)
function parents(plan) {
  let top = 0
  return plan.map((g, gi) => {
    if (!g.head || g.head.level === 1) top = gi
    return top
  })
}

// Расшифровка в виде плана: разделы из оглавления, под ними абзацы.
// Разделы свёрнуты, открыт только тот, что сейчас идёт в видео; остальные — по клику.
export default function Transcript({ segments, outline, time, onSeek, langSwitch }) {
  const active = activeIndex(segments, time)
  const list = useRef()
  const [follow, setFollow] = useState(true)
  const [open, setOpen] = useState(() => new Set())
  const userScroll = useRef(0)
  const plan = useMemo(() => buildPlan(segments, outline), [segments, outline])
  const parent = useMemo(() => parents(plan), [plan])
  const tops = useMemo(() => [...new Set(parent)], [parent])
  const currentGroup = plan.findIndex((g) => active >= g.pars[0][0].i && active <= g.pars.at(-1).at(-1).i)
  const currentTop = currentGroup >= 0 ? parent[currentGroup] : -1

  // Когда видео переходит в новый раздел — раскрываем его (свёрнутый вручную не трогаем, пока раздел тот же)
  useEffect(() => {
    if (follow && currentTop >= 0) setOpen((o) => (o.has(currentTop) ? o : new Set(o).add(currentTop)))
  }, [currentTop, follow])

  useEffect(() => {
    if (!follow || active < 0 || Date.now() - userScroll.current < 4000) return
    const el = list.current?.querySelector(`[data-i="${active}"]`)
    if (el) {
      const box = list.current
      const top = el.offsetTop - box.offsetTop - box.clientHeight / 3
      box.scrollTo({ top, behavior: 'smooth' })
    }
  }, [active, follow, open])

  const toggle = useCallback((gi) => {
    setOpen((o) => {
      const n = new Set(o)
      n.has(gi) ? n.delete(gi) : n.add(gi)
      return n
    })
  }, [])
  const allOpen = tops.every((t) => open.has(t))

  return (
    <div className="transcript">
      <div className={`transcript-tools row-between ${langSwitch ? 'with-lang' : ''}`}>
        <label className="muted small">
          <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> следовать за видео
        </label>
        {langSwitch}
        {tops.length > 1 && (
          <button className="link small" onClick={() => setOpen(allOpen ? new Set() : new Set(tops))}>
            {allOpen ? 'Свернуть всё' : 'Развернуть всё'}
          </button>
        )}
      </div>
      <div className="transcript-list" ref={list} onWheel={() => (userScroll.current = Date.now())}>
        <Plan plan={plan} parent={parent} open={open} active={active} onSeek={onSeek} onToggle={toggle} />
      </div>
    </div>
  )
}

const Plan = memo(function Plan({ plan, parent, open, active, onSeek, onToggle }) {
  return plan.map((g, gi) => {
    const first = g.pars[0][0].i
    const last = g.pars.at(-1).at(-1).i
    const current = active >= first && active <= last
    const top = parent[gi]
    const isOpen = !g.head || open.has(top)
    // Подраздел свёрнутого раздела не показываем вовсе
    if (g.head?.level === 2 && !open.has(top)) return null
    // Длительность раздела вместе с его подразделами
    let end = plan[gi].pars.at(-1).at(-1).s.end
    for (let k = gi + 1; k < plan.length && parent[k] === gi; k++) end = plan[k].pars.at(-1).at(-1).s.end
    return (
      <section key={gi} className={`tr-group ${current ? 'current' : ''} ${isOpen ? 'open' : 'closed'}`}>
        {g.head && g.head.level === 1 && (
          <div className="tr-head lvl1" onClick={() => onToggle(gi)} title={isOpen ? 'Свернуть раздел' : 'Развернуть раздел'}>
            <svg className="chevron" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M9 6l6 6-6 6" />
            </svg>
            <button
              className="timecode"
              onClick={(e) => {
                e.stopPropagation()
                onSeek(g.head.start)
              }}
              title="Перейти к началу раздела"
            >
              {fmtTime(g.head.start)}
            </button>
            <span className="tr-title">{g.head.title}</span>
            <span className="tr-len muted">{Math.max(1, Math.round((end - g.head.start) / 60))} мин</span>
          </div>
        )}
        {g.head && g.head.level === 2 && (
          <button className="tr-head lvl2" onClick={() => onSeek(g.head.start)} title="Перейти к подразделу">
            <span className="timecode">{fmtTime(g.head.start)}</span>
            <span>{g.head.title}</span>
          </button>
        )}
        {isOpen &&
          g.pars.map((p) => (
            <p key={p[0].i} className="tr-par">
              <button className="t" onClick={() => onSeek(p[0].s.start)} title="Перейти к этому месту">
                {fmtTime(p[0].s.start)}
              </button>
              <span className="tr-text">
                {p.map(({ s, i }) => (
                  <span
                    key={i}
                    data-i={i}
                    className={`seg ${i === active ? 'active' : ''}`}
                    onClick={() => onSeek(s.start)}
                  >
                    {s.text}{' '}
                  </span>
                ))}
              </span>
            </p>
          ))}
      </section>
    )
  })
})
