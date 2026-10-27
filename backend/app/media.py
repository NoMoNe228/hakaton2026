"""Видео: скачивание по ссылке (YouTube, Vimeo), приведение к формату для браузера, извлечение звука."""
import subprocess
from pathlib import Path

import imageio_ffmpeg

from .config import YT_COOKIES

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
BROWSER_FORMATS = {".mp4", ".webm"}


def _run(args):
    r = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg: {r.stderr.strip()[-500:]}")


_extractors = None


PLAYLIST_KINDS = ("Tab", "Playlist", "Channel", "User", "Search")
PLAYLIST_PARAMS = {"list", "index", "start_radio", "pp", "si", "feature", "t"}


def source_key(url: str) -> str | None:
    key = _source_key(url)
    # Видео, открытое из плейлиста: ключ должен быть у самого видео, а не у плейлиста
    if key and any(w in key.split(":")[0] for w in PLAYLIST_KINDS):
        from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

        parts = urlsplit(url)
        query = [(k, v) for k, v in parse_qsl(parts.query) if k not in PLAYLIST_PARAMS]
        if len(query) < len(parse_qsl(parts.query)):
            key = _source_key(urlunsplit(parts._replace(query=urlencode(query)))) or key
    return key


def _source_key(url: str) -> str | None:
    """«Сайт:номер видео» по ссылке, без выхода в интернет: youtu.be/X, youtube.com/watch?v=X&t=30
    и встроенный плеер дают один и тот же ключ. Работает для всех сайтов, которые знает yt-dlp."""
    global _extractors
    from yt_dlp.extractor import gen_extractor_classes

    if _extractors is None:
        _extractors = [ie for ie in gen_extractor_classes() if ie.ie_key() != "Generic"]
    # Ссылку на видео из плейлиста понимают и «видео», и «плейлист» — берём видео
    suitable = [ie for ie in _extractors if _safe_suitable(ie, url)]
    suitable.sort(key=lambda ie: any(w in ie.ie_key() for w in PLAYLIST_KINDS))
    for ie in suitable:
        try:
            vid = ie.get_temp_id(url)
            if not vid:
                m = ie._match_valid_url(url)
                vid = "_".join(v for v in (m.groupdict().values() if m else []) if v)
            if vid:
                return f"{ie.ie_key()}:{vid}"
        except Exception:
            continue
    return None


def _safe_suitable(ie, url) -> bool:
    try:
        return bool(ie.suitable(url))
    except Exception:
        return False


def download(url: str, folder: Path, on_progress=None) -> tuple[Path, str, str | None]:
    """Скачивает видео до 720p в mp4. Возвращает путь и название ролика."""
    import yt_dlp

    def hook(d):
        if on_progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                on_progress(d.get("downloaded_bytes", 0) / total)

    opts = {
        "format": "bv*[ext=mp4][height<=720]+ba[ext=m4a]/b[ext=mp4][height<=720]/bv*[height<=720]+ba/b",
        "merge_output_format": "mp4",
        "outtmpl": str(folder / "video.%(ext)s"),
        "ffmpeg_location": FFMPEG,
        "noplaylist": True,
        # Короткие запросы в несколько потоков: так меньше страдаем от ограничения скорости
        "http_chunk_size": 10 << 20,
        "concurrent_fragment_downloads": 8,
        "retries": 10,
        "fragment_retries": 10,
        # YouTube требует движок JavaScript; Node уже стоит для интерфейса
        "js_runtimes": {"node": {}, "deno": {}},
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
    }
    if _is_youtube(url) and YT_COOKIES.exists():
        # С входом в аккаунт YouTube не просит подтверждать «не робот»
        opts["cookiefile"] = str(YT_COOKIES)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as e:
        raise RuntimeError(explain_download_error(str(e))) from e
    files = [p for p in folder.glob("video.*") if p.suffix not in (".part", ".ytdl")]
    if not files:
        raise RuntimeError("Не удалось скачать видео по ссылке")
    video = files[0]
    if video.suffix.lower() not in BROWSER_FORMATS:
        video = to_browser_format(video)
    key = f"{info['extractor_key']}:{info['id']}" if info.get("extractor_key") and info.get("id") else None
    return video, info.get("title") or "Лекция", key


# Типичные отказы сайтов (текст yt-dlp) → что случилось и что делать, по-русски
DOWNLOAD_ERRORS = [
    (("confirm you’re not a bot", "confirm you're not a bot", "not a bot"),
     "YouTube просит подтвердить, что вы не робот (так бывает после многих скачиваний подряд). "
     "Выгрузите вход в YouTube из браузера: закройте браузер и запустите "
     "scripts/export_youtube_cookies.py, затем нажмите «Повторить». "
     "Или скачайте видео сами и загрузите файлом."),
    (("only works when logged-in", "login required", "sign in to view", "private video", "members-only",
      "join this channel"),
     "Видео доступно только после входа в аккаунт. Скачайте его сами и загрузите файлом."),
    (("video unavailable", "has been removed", "this video is not available", "does not exist", "http error 404"),
     "Видео недоступно: его удалили, закрыли или ссылка неверная."),
    (("not available in your country", "geo restrict", "blocked it in your country"),
     "Видео недоступно в вашей стране. Скачайте его другим способом и загрузите файлом."),
    (("unsupported url",),
     "По этой ссылке не нашлось видео. Нужна ссылка на страницу с роликом: YouTube, RuTube, VK Видео, Vimeo."),
    (("age-restricted", "age restricted", "confirm your age", "inappropriate for some users"),
     "Видео с ограничением по возрасту: его отдают только после входа в аккаунт. Загрузите его файлом."),
    (("unable to download webpage", "timed out", "connection", "getaddrinfo", "network is unreachable",
      "remote end closed"),
     "Не удалось связаться с сайтом видео. Проверьте интернет и нажмите «Повторить»."),
]


def _is_youtube(url: str) -> bool:
    host = url.split("//", 1)[-1].split("/", 1)[0].lower()
    return host.endswith(("youtube.com", "youtu.be", "youtube-nocookie.com"))


def explain_download_error(text: str) -> str:
    low = text.lower()
    for needles, message in DOWNLOAD_ERRORS:
        if any(n in low for n in needles):
            return message
    # Незнакомая ошибка: убираем служебный префикс и советы по ключам командной строки
    short = text.replace("ERROR: ", "").split(" Use --")[0].split(" See  ")[0].strip()
    return f"Не удалось скачать видео: {short[:200]}"


def to_browser_format(src: Path) -> Path:
    """MOV, MKV, AVI и т.п. перепаковываются в mp4, чтобы браузер мог их показать."""
    dst = src.with_name("video.mp4")
    try:
        _run(["-i", str(src), "-c", "copy", "-movflags", "+faststart", str(dst)])
    except RuntimeError:
        _run(["-i", str(src), "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
              "-c:a", "aac", "-movflags", "+faststart", str(dst)])
    src.unlink(missing_ok=True)
    return dst


def extract_audio(video: Path, out: Path) -> Path:
    """Звуковая дорожка: моно, 16 кГц — формат, который ждёт модель распознавания речи."""
    _run(["-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out)])
    return out


def thumbnail(video: Path, out: Path, at: float = 10.0) -> Path:
    """Кадр из видео для карточки лекции (ширина 480)."""
    _run(["-ss", f"{at:.1f}", "-i", str(video), "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "4", str(out)])
    return out


def duration(path: Path) -> float | None:
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    for line in r.stderr.splitlines():
        line = line.strip()
        if line.startswith("Duration:"):
            h, m, s = line.split(",")[0].split()[1].split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    return None


