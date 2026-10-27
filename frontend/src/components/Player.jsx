import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import Plyr from 'plyr'

const RU = {
  restart: 'Сначала',
  rewind: 'Назад на {seektime} с',
  play: 'Смотреть',
  pause: 'Пауза',
  fastForward: 'Вперёд на {seektime} с',
  seek: 'Перемотка',
  played: 'Просмотрено',
  buffered: 'Загружено',
  currentTime: 'Текущее время',
  duration: 'Длительность',
  volume: 'Громкость',
  mute: 'Без звука',
  unmute: 'Включить звук',
  enableCaptions: 'Включить субтитры',
  disableCaptions: 'Выключить субтитры',
  enterFullscreen: 'Во весь экран',
  exitFullscreen: 'Выйти из полноэкранного режима',
  settings: 'Настройки',
  speed: 'Скорость',
  normal: 'Обычная',
  quality: 'Качество',
  captions: 'Субтитры',
  disabled: 'Выключены',
  enabled: 'Включены',
}

// Видеоплеер Plyr. Сам элемент <video> создаём вручную: Plyr перестраивает DOM вокруг него,
// и React не должен этим узлом управлять.
// tracks — субтитры [{src, lang, label}] (оригинал и перевод), track — какой из них показывать.
const Player = forwardRef(function Player({ src, tracks = [], track = 0, startAt, onTime }, ref) {
  const box = useRef()
  const player = useRef()
  const video = useRef()
  const resume = useRef(null) // где остановились, если плеер пересоздаётся (появились субтитры перевода)
  const trackRef = useRef(track)
  trackRef.current = track
  const tracksKey = JSON.stringify(tracks)
  const onTimeRef = useRef(onTime)
  onTimeRef.current = onTime

  useImperativeHandle(ref, () => ({
    seek(t, play = true) {
      const v = video.current
      if (!v) return
      const go = () => {
        v.currentTime = Math.max(0, t)
        if (play) v.play().catch(() => {})
      }
      v.readyState >= 1 ? go() : v.addEventListener('loadedmetadata', go, { once: true })
    },
    time: () => video.current?.currentTime || 0,
  }))

  useEffect(() => {
    const v = document.createElement('video')
    v.setAttribute('playsinline', '')
    v.setAttribute('crossorigin', 'anonymous')
    v.preload = 'metadata'
    v.src = src
    tracks.forEach((t, i) => {
      const tr = document.createElement('track')
      tr.kind = 'captions'
      tr.label = t.label
      tr.srclang = t.lang
      tr.src = t.src
      tr.default = i === trackRef.current
      v.appendChild(tr)
    })
    box.current.appendChild(v)
    video.current = v
    const p = new Plyr(v, {
      i18n: RU,
      seekTime: 10,
      captions: { active: true, update: true, language: 'auto' },
      keyboard: { focused: true, global: false },
      speed: { selected: 1, options: [0.75, 1, 1.25, 1.5, 1.75, 2] },
      controls: ['play-large', 'rewind', 'play', 'fast-forward', 'progress', 'current-time', 'duration', 'mute',
        'volume', 'captions', 'settings', 'fullscreen'],
    })
    player.current = p
    const tick = () => onTimeRef.current?.(v.currentTime)
    v.addEventListener('timeupdate', tick)
    v.addEventListener('seeked', tick)
    const back = resume.current?.src === src ? resume.current : null
    const at = back?.time || startAt
    if (at) {
      const playing = back?.playing
      v.addEventListener('loadedmetadata', () => {
        v.currentTime = at
        if (playing) v.play().catch(() => {})
      }, { once: true })
    }
    p.on('ready', () => {
      if (tracks.length > 1) p.currentTrack = trackRef.current
    })
    return () => {
      resume.current = { src, time: v.currentTime, playing: !v.paused }
      v.removeEventListener('timeupdate', tick)
      p.destroy()
      if (box.current) box.current.innerHTML = ''
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src, tracksKey])

  // Переключили язык расшифровки — субтитры следом
  useEffect(() => {
    const p = player.current
    // Выключенные субтитры не включаем — только меняем дорожку, когда они показаны
    if (p && tracks.length > 1 && p.currentTrack !== -1 && p.currentTrack !== track) p.currentTrack = track
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [track, tracksKey])

  return <div className="player" ref={box} />
})

export default Player
