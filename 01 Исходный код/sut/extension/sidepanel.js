// Боковая панель «Суть»: находит лекцию для видео на открытой странице и показывает
// оглавление, расшифровку, конспект и поиск. Видео на странице перематывается по клику.
// Адрес сервиса и вход берутся из настроек панели (шестерёнка вверху)
const SITE = 'https://sut.foreio.tech'
const LOCAL = 'http://127.0.0.1:8000'
let API = SITE
let AUTH = '' // заголовок Authorization для сайта с входом по паролю
const STATUS = {
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

// ---------- Связь со страницей (в отладке подменяется через window.SUT_BRIDGE) ----------

function chromeBridge() {
  const injected = new Set()
  return {
    async tab() {
      const [t] = await chrome.tabs.query({ active: true, currentWindow: true })
      return t
    },
    async send(tabId, msg) {
      try {
        const r = await chrome.tabs.sendMessage(tabId, msg)
        if (r) return r
      } catch {}
      // Вкладка открыта до установки расширения — подключаем скрипт страницы сейчас
      if (!injected.has(tabId)) {
        injected.add(tabId)
        try {
          await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, files: ['content.js'] })
          return (await chrome.tabs.sendMessage(tabId, msg)) || null
        } catch {}
      }
      return null
    },
    onChange(cb) {
      chrome.tabs.onActivated.addListener(() => cb())
      chrome.tabs.onUpdated.addListener((id, info) => {
        if (id === st.tab?.id && (info.url || info.status === 'complete')) cb()
      })
    },
    open(url) {
      chrome.tabs.create({ url })
    },
  }
}
const bridge = window.SUT_BRIDGE || chromeBridge()

// ---------- Общее ----------

const $ = (sel) => document.querySelector(sel)
const app = $('#app')
const esc = (s) =>
  String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])

function fmt(sec) {
  sec = Math.max(0, Math.floor(sec || 0))
  const h = Math.floor(sec / 3600)
  const m = String(Math.floor((sec % 3600) / 60)).padStart(2, '0')
  const s = String(sec % 60).padStart(2, '0')
  return h ? `${h}:${m}:${s}` : `${m}:${s}`
}

// ---------- Настройки: где работает «Суть» и вход на сайт ----------

const store = {
  async get() {
    try {
      if (window.chrome?.storage?.local) return (await chrome.storage.local.get('sut')).sut || null
      return JSON.parse(localStorage.getItem('sut') || 'null')
    } catch {
      return null
    }
  },
  async set(v) {
    if (window.chrome?.storage?.local) return chrome.storage.local.set({ sut: v })
    localStorage.setItem('sut', JSON.stringify(v))
  },
}

const authHeader = (login, password) =>
  login ? 'Basic ' + btoa(unescape(encodeURIComponent(`${login}:${password}`))) : ''

const isLocal = (url) => /^https?:\/\/(127\.0\.0\.1|localhost)(:|\/|$)/.test(url)

function applySettings(cfg) {
  API = (cfg?.server || SITE).replace(/\/+$/, '')
  AUTH = authHeader(cfg?.login, cfg?.password)
}

class AuthError extends Error {}

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) }
  if (AUTH) headers.Authorization = AUTH
  const r = await fetch(API + path, { ...opts, headers })
  if (r.status === 401) throw new AuthError('Неверный логин или пароль')
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText)
  return r.json()
}

async function showSettings(note) {
  stopTimers()
  st.gen++
  const cfg = (await store.get()) || { server: SITE }
  app.innerHTML = `<form class="alert settings" id="settings">
    <p><b>Подключение к «Сути»</b></p>
    ${note ? `<p class="muted">${esc(note)}</p>` : ''}
    <div class="choice">
      <button type="button" data-preset="${SITE}">Сайт sut.foreio.tech</button>
      <button type="button" data-preset="${LOCAL}">Этот компьютер</button>
    </div>
    <label>Адрес сервиса<input name="server" value="${esc(cfg.server || SITE)}" placeholder="https://…" /></label>
    <div id="cred">
      <label>Логин<input name="login" value="${esc(cfg.login || '')}" autocomplete="username" /></label>
      <label>Пароль<input name="password" type="password" value="${esc(cfg.password || '')}" autocomplete="current-password" /></label>
      <p class="muted small">Те же, что для входа на сайт. Хранятся только в этом браузере.</p>
    </div>
    <button class="btn" id="save">Проверить и сохранить</button>
    <div id="msg" class="small" style="margin-top:8px"></div>
  </form>`
  const f = $('#settings')
  const sync = () => {
    const local = isLocal(f.server.value.trim())
    $('#cred').style.display = local ? 'none' : ''
    f.querySelectorAll('[data-preset]').forEach((b) => b.classList.toggle('on', b.dataset.preset === f.server.value.trim()))
  }
  f.querySelectorAll('[data-preset]').forEach((b) =>
    b.addEventListener('click', () => {
      f.server.value = b.dataset.preset
      sync()
    }),
  )
  f.server.addEventListener('input', sync)
  sync()
  f.addEventListener('submit', async (e) => {
    e.preventDefault()
    const server = f.server.value.trim().replace(/\/+$/, '')
    const local = isLocal(server)
    const next = { server, login: local ? '' : f.login.value.trim(), password: local ? '' : f.password.value }
    const msg = $('#msg')
    msg.style.color = ''
    msg.textContent = 'Проверяю…'
    const saved = { API, AUTH }
    applySettings(next)
    try {
      await api('/api/health')
      await store.set(next)
      setServer(true)
      init()
    } catch (err) {
      API = saved.API
      AUTH = saved.AUTH
      msg.style.color = 'var(--danger)'
      msg.textContent =
        err instanceof AuthError ? err.message : `Сервис по этому адресу не отвечает (${err.message || 'нет связи'})`
    }
  })
}

function setServer(ok) {
  $('#server').className = `server ${ok ? 'ok' : 'bad'}`
  $('#server').title = ok ? 'Сервер «Суть» работает' : 'Сервер «Суть» не отвечает'
}

const st = {
  tab: null,
  url: '',
  lec: null,
  raw: [], // фразы с сервера (оригинал и перевод)
  segments: [], // фразы на выбранном языке — по ним подсветка и перемотка
  plan: [],
  view: 'text',
  active: -1,
  follow: true,
  userScroll: 0,
  timers: [],
  gen: 0,
}

function stopTimers() {
  st.timers.forEach(clearInterval)
  st.timers = []
}

// ---------- Что на странице ----------

async function init() {
  const gen = ++st.gen
  stopTimers()
  const cfg = await store.get()
  // Первый запуск: сначала спросим, где работает «Суть» (на стенде — сразу этот компьютер)
  if (!cfg && !window.SUT_BRIDGE) {
    return showSettings('Выберите, где работает «Суть». Обычно это сайт — нужны логин и пароль от него.')
  }
  applySettings(cfg || { server: LOCAL })
  const tab = await bridge.tab()
  st.tab = tab
  st.url = tab?.url || ''
  st.lec = null
  if (!tab || !/^https?:/.test(st.url) || st.url.startsWith(API)) {
    return message('Откройте страницу с видео — например, лекцию на YouTube или RuTube.')
  }
  let info
  try {
    info = await api(`/api/lookup?url=${encodeURIComponent(st.url)}`)
    setServer(true)
  } catch (err) {
    setServer(false)
    return serverDown(err)
  }
  // Видео во встроенном плеере (iframe): пробуем адрес фрейма, где нашлось видео
  if (!info.lecture) {
    const s = await bridge.send(tab.id, { type: 'sut:state' })
    if (s?.frame && s.frame !== st.url) {
      const inFrame = await api(`/api/lookup?url=${encodeURIComponent(s.frame)}`).catch(() => null)
      if (inFrame && (inFrame.lecture || (!info.supported && inFrame.supported))) {
        info = inFrame
        st.url = s.frame
      }
    }
  }
  if (gen !== st.gen) return
  if (info.lecture) return openLecture(info.lecture.id, gen)
  if (info.supported) return notProcessed()
  message('«Суть» не умеет скачивать видео с этой страницы. Скачайте видео и загрузите файлом в сервис.', true)
}

function message(text, withOpen) {
  app.innerHTML = `<div class="alert"><p>${esc(text)}</p>${
    withOpen ? '<button class="link" id="open-app">Открыть «Суть»</button>' : ''
  }</div>`
  $('#open-app')?.addEventListener('click', () => bridge.open(API))
}

function serverDown(err) {
  if (err instanceof AuthError) return showSettings('Сайт не принял логин или пароль. Проверьте их.')
  const where = isLocal(API)
    ? 'Запустите start.ps1 в папке проекта и нажмите «Повторить».'
    : `Сайт ${esc(API.replace(/^https?:\/\//, ''))} работает, пока включён компьютер с сервисом. Попробуйте чуть позже.`
  app.innerHTML = `<div class="alert">
    <p><b>«Суть» сейчас не отвечает.</b></p>
    <p class="muted">${where}</p>
    <button class="btn" id="retry">Повторить</button>
    <button class="link" id="to-settings" style="margin-left:10px">Настройки</button></div>`
  $('#retry').addEventListener('click', init)
  $('#to-settings').addEventListener('click', () => showSettings())
}

function notProcessed() {
  const title = (st.tab.title || '').replace(/\s*[-–|]\s*(YouTube|RUTUBE|Rutube|ВКонтакте|VK Видео|Vimeo)\s*$/i, '')
  app.innerHTML = `<div class="alert">
    <p><b>Это видео ещё не обработано.</b></p>
    <p class="muted">«Суть» скачает его, распознает речь и построит оглавление и конспект — своими моделями, без внешних сервисов.</p>
    <button class="btn" id="process">Обработать в «Сути»</button>
    <div id="err" class="small" style="color:var(--danger);margin-top:8px"></div></div>`
  $('#process').addEventListener('click', async (e) => {
    e.target.disabled = true
    e.target.textContent = 'Добавляю…'
    try {
      const lec = await api('/api/lectures/url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: st.url, title }),
      })
      openLecture(lec.id, st.gen)
    } catch (err) {
      $('#err').textContent = err.message
      e.target.disabled = false
      e.target.textContent = 'Обработать в «Сути»'
    }
  })
}

// ---------- Лекция ----------

const searchable = (s) => s === 'indexed' || s === 'summarizing' || s === 'ready'
const summaryPending = (s) => s === 'indexed' || s === 'summarizing'

async function openLecture(id, gen) {
  const lec = await api(`/api/lectures/${id}`)
  if (gen !== st.gen) return
  st.lec = lec
  if (!searchable(lec.status)) {
    renderProgress(lec)
    const t = setInterval(async () => {
      const l = await api(`/api/lectures/${id}`).catch(() => null)
      if (!l || gen !== st.gen) return
      if (searchable(l.status) || l.status === 'error') {
        clearInterval(t)
        openLecture(id, gen)
      } else renderProgress(l)
    }, 2000)
    st.timers.push(t)
    return
  }
  st.raw = await api(`/api/lectures/${id}/segments`)
  if (gen !== st.gen) return
  rebuildPlan()
  st.active = -1
  renderLecture()
  watchTranslation(id, gen)
  // Время видео на странице — для подсветки текущей фразы
  st.timers.push(setInterval(tick, 500))
  // Конспект ещё пишется — обновим, когда будет готов
  if (summaryPending(lec.status)) {
    const t = setInterval(async () => {
      const l = await api(`/api/lectures/${id}`).catch(() => null)
      if (l && !summaryPending(l.status) && gen === st.gen) {
        clearInterval(t)
        st.lec = l
        rebuildPlan()
        renderLecture()
      }
    }, 3000)
    st.timers.push(t)
  }
}

function renderProgress(lec) {
  if (lec.status === 'error') {
    app.innerHTML = `<div class="alert"><p><b>Не удалось обработать видео.</b></p><p class="muted">${esc(lec.error)}</p></div>`
    return
  }
  app.innerHTML = `<div class="lec-head"><h1>${esc(lec.title)}</h1></div>
    <div class="alert"><b>${esc(STATUS[lec.status] || lec.status)}</b> · ${Math.round(lec.progress)}%
      <div class="bar"><div style="width:${lec.progress}%"></div></div>
      <p class="muted small" style="margin-top:8px">Расшифровка и поиск появятся здесь сами, как только речь будет распознана.</p></div>`
}

function renderLecture() {
  const l = st.lec
  const lang = { ru: 'русский', en: 'английский' }[l.language] || l.language || ''
  app.innerHTML = `
    <div class="lec-head">
      <h1>${esc(l.title)}</h1>
      <div class="muted small">${fmt(l.duration)}${lang ? ' · ' + esc(lang) : ''} ·
        <button class="link small" id="open-app">открыть в «Сути»</button></div>
    </div>
    <form class="search" id="search">
      <input name="q" placeholder="Найти в этом видео по смыслу" autocomplete="off" />
      <button class="btn">Найти</button>
    </form>
    <nav class="tabs">
      <button data-view="outline">План</button>
      <button data-view="text">Текст</button>
      <button data-view="summary">Конспект</button>
    </nav>
    <div class="body" id="body"></div>`
  $('#open-app').addEventListener('click', () => bridge.open(`${API}/lecture/${l.id}`))
  $('#search').addEventListener('submit', search)
  app.querySelectorAll('.tabs button').forEach((b) =>
    b.addEventListener('click', () => {
      st.view = b.dataset.view
      renderView()
    }),
  )
  const body = $('#body')
  body.addEventListener('wheel', () => (st.userScroll = Date.now()))
  body.addEventListener('click', onBodyClick)
  renderView()
}

function renderView() {
  app.querySelectorAll('.tabs button').forEach((b) => b.classList.toggle('on', b.dataset.view === st.view))
  const body = $('#body')
  if (st.view === 'outline') body.innerHTML = outlineHtml()
  else if (st.view === 'summary') body.innerHTML = summaryHtml()
  else body.innerHTML = textHtml()
  st.active = -1
  highlight(st.lastTime ?? 0)
}

// Клики внутри панели: перемотка по таймкоду, сворачивание разделов, язык текста
function onBodyClick(e) {
  const langBtn = e.target.closest('[data-lang]')
  if (langBtn) {
    setLangPref(langBtn.dataset.lang)
    rebuildPlan()
    return renderView()
  }
  if (e.target.closest('[data-retranslate]')) {
    api(`/api/lectures/${st.lec.id}/translate`, { method: 'POST' }).catch(() => {})
    st.lec.translation.error = null
    return updateLangSwitch()
  }
  const back = e.target.closest('[data-back]')
  if (back) return renderView()
  const head = e.target.closest('.g-head')
  const seekEl = e.target.closest('[data-t]')
  if (head && !seekEl) {
    head.parentElement.classList.toggle('open')
    head.parentElement.classList.toggle('closed')
    return
  }
  if (seekEl) seek(Number(seekEl.dataset.t))
}

async function seek(t) {
  const r = await bridge.send(st.tab.id, { type: 'sut:seek', t, play: true })
  if (!r) toast('Не нашёл видео на странице')
  st.userScroll = 0
}

function toast(text) {
  const el = document.createElement('div')
  el.className = 'alert small'
  el.style.cssText = 'position:fixed;left:0;right:0;bottom:0;margin:10px'
  el.textContent = text
  document.body.appendChild(el)
  setTimeout(() => el.remove(), 2500)
}

// ---------- Подсветка текущего места ----------

function activeIndex(t) {
  const s = st.segments
  let lo = 0
  let hi = s.length - 1
  let ans = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (s[mid].start <= t + 0.05) {
      ans = mid
      lo = mid + 1
    } else hi = mid - 1
  }
  return ans
}

async function tick() {
  if (!st.tab || !st.segments.length) return
  const r = await bridge.send(st.tab.id, { type: 'sut:state' })
  if (r && typeof r.t === 'number') {
    st.lastTime = r.t
    highlight(r.t)
  }
}

function highlight(t) {
  const i = activeIndex(t)
  if (i === st.active) return
  st.active = i
  const body = $('#body')
  if (!body) return
  body.querySelectorAll('.seg.active').forEach((el) => el.classList.remove('active'))
  body.querySelectorAll('.current').forEach((el) => el.classList.remove('current'))
  if (i < 0) return
  // Текущий раздел в плане и в тексте
  body.querySelectorAll('[data-from]').forEach((el) => {
    if (i >= Number(el.dataset.from) && i <= Number(el.dataset.to)) el.classList.add('current')
  })
  const seg = body.querySelector(`.seg[data-i="${i}"]`)
  if (!seg) return
  seg.classList.add('active')
  const grp = seg.closest('.grp')
  if (st.follow && grp?.classList.contains('closed') && !grp.dataset.userClosed) {
    grp.classList.replace('closed', 'open')
  }
  if (st.follow && Date.now() - st.userScroll > 4000) {
    const top = seg.offsetTop - body.offsetTop - body.clientHeight / 3
    body.scrollTo({ top, behavior: 'smooth' })
  }
}

// ---------- Язык текста: оригинал или перевод ----------

const LANG_KEY = 'sut.lang'
let langPref = null
try {
  langPref = localStorage.getItem(LANG_KEY)
} catch {}

function setLangPref(l) {
  langPref = l
  try {
    localStorage.setItem(LANG_KEY, l)
  } catch {}
}

// Перевод показываем, только когда он готов целиком; иначе — оригинал
function curLang() {
  const tr = st.lec?.translation
  if (!tr) return null
  return langPref === tr.tr && tr.ready ? tr.tr : tr.orig
}

// Перевод лежит в первой фразе предложения, у остальных его фраз text_tr пустой —
// склеиваем их в одну запись от начала первой фразы до конца последней
function merged(segments) {
  const out = []
  for (const s of segments) {
    if (s.text_tr === '' && out.length) out[out.length - 1] = { ...out[out.length - 1], end: s.end }
    else out.push({ ...s, text: s.text_tr || s.text })
  }
  return out
}

function rebuildPlan() {
  const tr = st.lec.translation
  st.segments = tr && curLang() === tr.tr ? merged(st.raw) : st.raw
  st.plan = buildPlan(st.segments, shownOutline())
  st.active = -1
}

// Заголовки оглавления (модель пишет их по-русски) — на языке текста, если есть их перевод
function shownOutline() {
  const outline = st.lec.outline
  const alt = st.lec.outline_alt
  if (!alt || curLang() !== alt.lang || outline?.length !== alt.sections?.length) return outline
  return outline.map((sec, i) => ({
    ...sec,
    title: alt.sections[i].title || sec.title,
    children: sec.children.map((c, j) => ({ ...c, title: alt.sections[i].children?.[j] || c.title })),
  }))
}

function langSwitchHtml() {
  const tr = st.lec.translation
  if (!tr || !tr.total) return ''
  const code = (l) => (l || '').toUpperCase()
  const lang = curLang()
  const pct = Math.round((100 * tr.done) / tr.total)
  const second = tr.ready
    ? `<button data-lang="${tr.tr}" class="${lang === tr.tr ? 'on' : ''}" title="Перевод локальной моделью">${code(tr.tr)} <span class="note">· перевод</span></button>`
    : tr.error
      ? `<button data-retranslate="1" title="${esc(tr.error)}">${code(tr.tr)} <span class="note">· ошибка, повторить</span></button>`
      : `<button disabled title="Локальная модель переводит расшифровку">${code(tr.tr)} <span class="note">· готовится ${pct}%</span></button>`
  return `<span class="lang-switch" id="lang-switch"><button data-lang="${tr.orig}" class="${lang === tr.orig ? 'on' : ''}" title="Оригинал: текст, как его произнёс лектор">${code(tr.orig)}</button>${second}</span>`
}

function updateLangSwitch() {
  const el = $('#lang-switch')
  if (el) el.outerHTML = langSwitchHtml()
}

// Перевод готовится в фоне: показываем ход, а когда готов — берём фразы с переводом
function watchTranslation(id, gen) {
  const tr = st.lec.translation
  if (!tr || tr.ready || st.lec.status !== 'ready') return
  const t = setInterval(async () => {
    const l = await api(`/api/lectures/${id}`).catch(() => null)
    if (!l || gen !== st.gen) return
    st.lec = l
    if (l.translation?.ready) {
      clearInterval(t)
      st.raw = await api(`/api/lectures/${id}/segments`)
      if (gen !== st.gen) return
      rebuildPlan()
      if (st.view === 'outline') renderView()
      else updateLangSwitch()
    } else updateLangSwitch()
  }, 5000)
  st.timers.push(t)
}

// ---------- План и текст ----------

function headings(outline) {
  const out = []
  for (const sec of outline || []) {
    out.push({ title: sec.title, start: sec.start })
  }
  return out.sort((a, b) => a.start - b.start)
}

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

function textHtml() {
  const tools = `<div class="tools"><label class="muted small"><input type="checkbox" id="follow" ${
    st.follow ? 'checked' : ''
  }/> следовать за видео</label>${langSwitchHtml()}</div>`
  const html = st.plan
    .map((g) => {
      const from = g.pars[0][0].i
      const last = g.pars.at(-1).at(-1)
      const len = Math.max(1, Math.round((last.s.end - g.pars[0][0].s.start) / 60))
      const pars = g.pars
        .map(
          (p) => `<p class="par"><button class="t" data-t="${p[0].s.start}">${fmt(p[0].s.start)}</button><span>${p
            .map(({ s, i }) => `<span class="seg" data-i="${i}" data-t="${s.start}">${esc(s.text)} </span>`)
            .join('')}</span></p>`,
        )
        .join('')
      const head = g.head
        ? `<div class="g-head"><span class="chev">▶</span><button class="timecode" data-t="${g.head.start}">${fmt(
            g.head.start,
          )}</button><span class="g-title">${esc(g.head.title)}</span><span class="g-len">${len} мин</span></div>`
        : ''
      return `<section class="grp ${g.head ? 'closed' : 'open'}" data-from="${from}" data-to="${last.i}">${head}<div class="pars">${pars}</div></section>`
    })
    .join('')
  setTimeout(() => {
    $('#follow')?.addEventListener('change', (e) => (st.follow = e.target.checked))
    // Свёрнутый вручную раздел не раскрываем сами
    $('#body')
      .querySelectorAll('.g-head')
      .forEach((h) =>
        h.addEventListener('click', (e) => {
          if (e.target.closest('[data-t]')) return
          const grp = h.parentElement
          // Сейчас открыт — значит, пользователь его сворачивает
          grp.dataset.userClosed = grp.classList.contains('open') ? '1' : ''
        }),
      )
  })
  return tools + html
}

function outlineHtml() {
  const outline = shownOutline()
  if (!outline?.length) return pendingSummary()
  const items = outline
    .map((sec, k) => {
      // Диапазон фраз раздела — для подсветки текущего
      const next = outline[k + 1]?.start ?? Infinity
      const from = st.segments.findIndex((s) => s.start >= sec.start - 0.5)
      let to = st.segments.length - 1
      for (let j = Math.max(from, 0); j < st.segments.length; j++) if (st.segments[j].start >= next - 0.5) {
        to = j - 1
        break
      }
      const points = sec.children.length === 1
        ? sec.children[0].points.map((p) => `<li>${esc(p)}</li>`).join('')
        : sec.children
            .map((c) => `<li><button class="link small" data-t="${c.start}">${fmt(c.start)}</button> ${esc(c.title)}</li>`)
            .join('')
      return `<li data-from="${from}" data-to="${to}"><button class="o-row" data-t="${sec.start}"><span class="timecode">${fmt(
        sec.start,
      )}</span><span>${esc(sec.title)}</span></button>${points ? `<ul>${points}</ul>` : ''}</li>`
    })
    .join('')
  return `<ol class="outline">${items}</ol>`
}

function pendingSummary() {
  if (st.lec.status === 'indexed') return '<div class="pad muted">Конспект в очереди: сначала распознаются другие скачанные лекции.</div>'
  if (st.lec.status === 'summarizing') return '<div class="pad muted">Локальная модель пишет конспект и оглавление…</div>'
  return `<div class="pad muted">${esc(st.lec.summary_error || 'Оглавления нет.')}</div>`
}

function summaryHtml() {
  const s = st.lec.summary
  if (!s) return pendingSummary()
  const points = (s.key_points || []).map((p) => `<li>${esc(p)}</li>`).join('')
  const terms = (st.lec.terms || [])
    .map(
      (t) => `<div class="term"><button class="timecode" data-t="${t.start}">${fmt(t.start)}</button><b>${esc(
        t.term,
      )}</b><div>${esc(t.definition)}</div></div>`,
    )
    .join('')
  return `<div class="summary"><p>${esc(s.text)}</p>${points ? `<h3>Главное</h3><ul>${points}</ul>` : ''}${
    terms ? `<h3>Термины</h3>${terms}` : ''
  }</div>`
}

// ---------- Поиск ----------

async function search(e) {
  e.preventDefault()
  const q = e.target.q.value.trim()
  if (!q) return
  const body = $('#body')
  body.innerHTML = '<div class="pad muted">Ищу по смыслу…</div>'
  try {
    const { results } = await api(`/api/search?q=${encodeURIComponent(q)}&lecture_id=${st.lec.id}`)
    const list = results
      .map((r) => {
        let text = esc(r.text)
        if (r.highlights?.length) {
          let out = ''
          let pos = 0
          for (const [a, b] of r.highlights) {
            out += esc(r.text.slice(pos, a)) + `<mark>${esc(r.text.slice(a, b))}</mark>`
            pos = b
          }
          text = out + esc(r.text.slice(pos))
        }
        return `<li class="result" data-t="${r.jump}"><span class="timecode">▶ ${fmt(r.jump)}</span><p>${text}</p></li>`
      })
      .join('')
    body.innerHTML = `<div class="tools"><span class="muted small">${
      results.length ? `Найдено: ${results.length}` : 'Ничего близкого по смыслу'
    }</span><button class="link small" data-back>← назад</button></div><ol class="results">${list}</ol>`
  } catch (err) {
    body.innerHTML = `<div class="pad" style="color:var(--danger)">${esc(err.message)}</div>`
  }
}

$('#gear').addEventListener('click', () => showSettings())

bridge.onChange(() => {
  // Сайты вроде YouTube меняют адрес без перезагрузки — проверяем, сменилось ли видео
  bridge.tab().then((t) => {
    if (t && (t.id !== st.tab?.id || t.url !== st.tab?.url)) init()
  })
})
init()
