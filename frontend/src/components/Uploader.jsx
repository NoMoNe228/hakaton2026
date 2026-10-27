import { useRef, useState } from 'react'
import { api, uploadFile } from '../api.js'
import { useNarrow } from '../useNarrow.js'

// Добавление лекции: файл (перетащить или выбрать) или ссылка на YouTube / Vimeo
export default function Uploader({ onAdded }) {
  const [drag, setDrag] = useState(false)
  const [uploads, setUploads] = useState([]) // [{name, progress, error}]
  const [url, setUrl] = useState('')
  const [urlBusy, setUrlBusy] = useState(false)
  const [urlError, setUrlError] = useState('')
  const narrow = useNarrow()
  const input = useRef()

  const send = async (files) => {
    for (const file of files) {
      const key = `${file.name}-${Date.now()}`
      setUploads((u) => [...u, { key, name: file.name, progress: 0 }])
      const patch = (p) => setUploads((u) => u.map((x) => (x.key === key ? { ...x, ...p } : x)))
      try {
        await uploadFile(file, (progress) => patch({ progress }))
        setUploads((u) => u.filter((x) => x.key !== key))
        onAdded()
      } catch (e) {
        patch({ error: e.message })
      }
    }
  }

  const addUrl = async (e) => {
    e.preventDefault()
    setUrlError('')
    setUrlBusy(true)
    try {
      await api.addUrl(url.trim())
      setUrl('')
      onAdded()
    } catch (err) {
      setUrlError(err.message)
    } finally {
      setUrlBusy(false)
    }
  }

  return (
    <section className="uploader">
      <div
        className={`dropzone ${drag ? 'drag' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          setDrag(true)
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDrag(false)
          send([...e.dataTransfer.files])
        }}
        onClick={() => input.current.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && input.current.click()}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3" />
        </svg>
        <div>
          <b>Перетащите видео сюда</b> или нажмите, чтобы выбрать
          <div className="muted small">MP4, WebM, MOV, MKV — можно несколько файлов сразу</div>
        </div>
        <input
          ref={input}
          type="file"
          accept="video/*,.mkv"
          multiple
          hidden
          onChange={(e) => {
            send([...e.target.files])
            e.target.value = ''
          }}
        />
      </div>

      <form className="urlform" onSubmit={addUrl}>
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder={narrow ? '…или ссылка на видео' : '…или ссылка на YouTube, RuTube, VK Видео, Vimeo'}
          aria-label="Ссылка на видео"
        />
        <button type="submit" disabled={!url.trim() || urlBusy}>
          {urlBusy ? 'Добавляю…' : 'Добавить'}
        </button>
      </form>
      {urlError && <div className="alert">{urlError}</div>}

      {uploads.map((u) => (
        <div key={u.key} className="upload-row">
          <span className="ellipsis">{u.name}</span>
          {u.error ? (
            <span className="alert-text">{u.error}</span>
          ) : (
            <div className="bar">
              <div style={{ width: `${Math.round(u.progress * 100)}%` }} />
            </div>
          )}
        </div>
      ))}
    </section>
  )
}
