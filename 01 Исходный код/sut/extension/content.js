// Скрипт страницы: находит главное видео (в том числе во встроенном плеере-iframe)
// и выполняет команды боковой панели — сообщить время, перемотать.
;(() => {
  if (window.__sutContent) return
  window.__sutContent = true

  const area = (v) => {
    const r = v.getBoundingClientRect()
    return r.width * r.height
  }

  function mainVideo() {
    const vids = [...document.querySelectorAll('video')].filter((v) => v.currentSrc || v.src || v.readyState > 0)
    if (!vids.length) return null
    return vids.sort((a, b) => area(b) - area(a))[0]
  }

  chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
    if (!msg || !String(msg.type).startsWith('sut:')) return
    const v = mainVideo()
    // В этом фрейме видео нет — промолчим, ответит фрейм с плеером
    if (!v) return
    if (msg.type === 'sut:state') {
      reply({ t: v.currentTime, paused: v.paused, duration: v.duration, frame: location.href })
    } else if (msg.type === 'sut:seek') {
      v.currentTime = Math.max(0, msg.t)
      if (msg.play) v.play().catch(() => {})
      reply({ ok: true })
    }
  })
})()
