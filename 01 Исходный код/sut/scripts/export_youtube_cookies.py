"""Выгружает вход в YouTube из браузера в файл data/youtube_cookies.txt.

Зачем: после многих скачиваний YouTube начинает просить «подтвердите, что вы не робот».
С входом в аккаунт скачивание снова работает. Сервис берёт вход из этого файла.

Браузер на время выгрузки нужно закрыть полностью: работающий браузер не даёт прочитать свои cookies.
Берутся только cookies YouTube и Google; файл лежит в data/ и в git не попадает.
Значения cookies скрипт не печатает — только их количество.

Запуск: .venv\\Scripts\\python.exe scripts\\export_youtube_cookies.py [vivaldi|chrome|edge|firefox|opera|brave]
"""
import sys
from pathlib import Path

from yt_dlp.cookies import YoutubeDLCookieJar, extract_cookies_from_browser

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "youtube_cookies.txt"
DOMAINS = ("youtube.com", "google.com")
# Признаки того, что в браузере выполнен вход в аккаунт Google
LOGIN = {"SID", "__Secure-1PSID", "__Secure-3PSID", "SAPISID", "LOGIN_INFO"}


def main():
    browser = (sys.argv[1] if len(sys.argv) > 1 else "vivaldi").lower()
    try:
        jar = extract_cookies_from_browser(browser)
    except Exception as e:
        msg = str(e)
        if "Could not copy" in msg:
            print(f"Не удалось прочитать cookies: {browser} ещё запущен. Закройте его полностью и запустите снова.")
        else:
            print(f"Не удалось прочитать cookies из {browser}: {msg[:200]}")
        sys.exit(1)

    out = YoutubeDLCookieJar(str(OUT))
    for c in jar:
        if c.domain.lstrip(".").endswith(DOMAINS):
            out.set_cookie(c)
    names = {c.name for c in out}
    if not len(out):
        print(f"В {browser} нет cookies YouTube — откройте youtube.com в этом браузере и войдите в аккаунт.")
        sys.exit(1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.save(ignore_discard=True, ignore_expires=True)
    login = bool(names & LOGIN)
    print(f"Сохранено cookies YouTube и Google: {len(out)} → {OUT}")
    print("Вход в аккаунт найден." if login else
          "Внимание: признаков входа в аккаунт нет — войдите в YouTube в этом браузере и выгрузите заново.")


if __name__ == "__main__":
    main()
