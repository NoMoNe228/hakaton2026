"""Сквозная проверка работающего сервера: загрузка лекции → обработка → поиск → вопрос.

Запуск (сервер уже работает на :8000):
  .venv\\Scripts\\python.exe scripts\\smoke_test.py путь\\к\\видео.mp4 "запрос 1" "запрос 2"
  .venv\\Scripts\\python.exe scripts\\smoke_test.py --id <id лекции> "запрос"   — для уже загруженной
"""
import json
import sys
import time
from pathlib import Path

import httpx

API = "http://127.0.0.1:8000/api"


def fmt(sec):
    sec = int(sec)
    return f"{sec // 60:02d}:{sec % 60:02d}"


def main():
    args = sys.argv[1:]
    c = httpx.Client(timeout=600)
    if args and args[0] == "--id":
        lid, queries = args[1], args[2:]
    else:
        path, queries = Path(args[0]), args[1:]
        t0 = time.time()
        with path.open("rb") as f:
            r = c.post(f"{API}/lectures/upload", files={"file": (path.name, f, "video/mp4")})
        r.raise_for_status()
        lid = r.json()["id"]
        print(f"Загружено за {time.time() - t0:.1f} с, id={lid}")

    t0, stage, stamps = time.time(), None, {}
    while True:
        lec = c.get(f"{API}/lectures/{lid}").json()
        if lec["status"] != stage:
            stage = lec["status"]
            stamps[stage] = time.time() - t0
            print(f"[{time.time() - t0:6.1f} с] {stage}")
        if stage in ("ready", "error"):
            break
        time.sleep(1)
    if stage == "error":
        print("ОШИБКА:", lec["error"])
        return
    dur = lec["duration"] or 0
    if "transcribing" in stamps and "indexing" in stamps:
        t = stamps["indexing"] - stamps["transcribing"]
        print(f"Расшифровка: {t:.0f} с на {dur / 60:.1f} мин видео ({dur / max(t, 1):.1f}× быстрее реального времени)")
    print("Язык:", lec["language"], "| Конспект:", "есть" if lec["summary"] else lec.get("summary_error"))
    if lec["summary"]:
        print("\nКОНСПЕКТ:", lec["summary"]["text"])
        for s in lec["outline"]:
            print(f"  [{fmt(s['start'])}] {s['title']}")
            for ch in s["children"]:
                print(f"      [{fmt(ch['start'])}] {ch['title']}")
        print("ТЕРМИНЫ:", ", ".join(t["term"] for t in lec["terms"]))

    for q in queries:
        t = time.time()
        res = c.get(f"{API}/search", params={"q": q}).json()["results"]
        print(f"\nПОИСК «{q}» — {time.time() - t:.2f} с, {len(res)} результатов")
        for r in res[:3]:
            print(f"  {r['score']:.2f} [{fmt(r['jump'])}] {r['lecture_title'][:30]}: {r['text'][:140]}")

    if queries:
        t = time.time()
        with c.stream("POST", f"{API}/ask", json={"question": queries[0], "lecture_id": lid}) as r:
            answer = ""
            for line in r.iter_lines():
                ev = json.loads(line)
                answer += ev.get("delta", "")
                if ev.get("error"):
                    answer += "ОШИБКА: " + ev["error"]
        print(f"\nВОПРОС «{queries[0]}» — {time.time() - t:.1f} с\n{answer}")


if __name__ == "__main__":
    main()
