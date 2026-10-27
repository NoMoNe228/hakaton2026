"""Перевод расшифровки локальной моделью: английская лекция → русский, русская (и любая другая) → английский.

Переводим целыми предложениями (фразы Whisper склеиваем до точки), пачками по нескольку соседних —
так у модели есть контекст. Перевод каждой пачки сразу пишется в базу,
поэтому прерванный перевод продолжается с того же места.
Заголовки оглавления (их модель пишет по-русски) переводим на второй язык лекции,
чтобы в любом режиме расшифровка была на одном языке.
"""
import bisect
import re

from . import db, llm

LANG_NAMES = {"ru": "русский", "en": "английский", "de": "немецкий", "fr": "французский", "es": "испанский",
              "it": "итальянский", "uk": "украинский", "zh": "китайский", "ja": "японский"}
BATCH = 6          # предложений в одном запросе


def target_lang(lang: str | None) -> str:
    """На какой язык переводим расшифровку."""
    return "en" if lang == "ru" else "ru"


def alt_lang(lang: str | None) -> str:
    """На какой язык переводим заголовки оглавления (сами они написаны по-русски)."""
    return "en" if not lang or lang == "ru" else lang


def _name(code):
    return LANG_NAMES.get(code, code)


def state(lec: dict) -> dict:
    """Сколько готово: для интерфейса — показать «перевод готовится» вместо пустого текста."""
    row = db.query("SELECT COUNT(*) AS total, COUNT(text_tr) AS done FROM segments WHERE lecture_id = ?",
                   (lec["id"],))[0]
    titles_ok = not lec.get("outline") or bool(lec.get("outline_alt"))
    return {"orig": lec.get("language") or "ru", "tr": target_lang(lec.get("language")),
            "alt": alt_lang(lec.get("language")), "done": row["done"], "total": row["total"],
            "ready": row["total"] > 0 and row["done"] == row["total"] and titles_ok,
            "error": lec.get("tr_error")}


def needed(lec: dict) -> bool:
    if lec["status"] != "ready":
        return False
    if lec.get("outline") and not lec.get("outline_alt"):
        return True
    return bool(db.query("SELECT 1 FROM segments WHERE lecture_id = ? AND text_tr IS NULL LIMIT 1", (lec["id"],)))


# Конец предложения: знак, пробел, затем заглавная буква или цифра (так «0.5» и «e.g. x» не режутся)
_SENT_END = re.compile(r"[.!?…]+[\"»)']*\s+(?=[\"«(\-–—]?\s?[A-ZА-ЯЁ0-9])")


def units(segs: list[dict]) -> list[tuple[list[int], str]]:
    """Делит расшифровку на куски для перевода: (номера фраз, текст из целых предложений).

    Whisper режет речь где придётся, посреди предложения, а обрывки маленькая модель переводит плохо —
    переносит слова в соседний пункт или не переводит вовсе. Поэтому текст делим на предложения,
    а кусок привязываем к фразам: он начинается с той фразы, где начинается его первое предложение.
    Перевод куска показывается с начала этой фразы. Длинную речь без точек режем по фразам (~350 знаков).
    """
    starts, full = [], ""
    for s in segs:
        starts.append(len(full))
        full += s["text"].strip() + " "
    first = {0: 0}  # фраза → где в ней начинается первое предложение
    for m in _SENT_END.finditer(full):
        first.setdefault(bisect.bisect_right(starts, m.end()) - 1, m.end())
    bounds = sorted(first)
    out = []
    for n, b in enumerate(bounds):
        e = bounds[n + 1] if n + 1 < len(bounds) else len(segs)
        a_off, b_off = first[b], first[e] if e < len(segs) else len(full)
        cur, cur_off = [b], a_off
        for k in range(b + 1, e):
            if b_off - cur_off > 450 and starts[k] - cur_off > 350:
                out.append((cur, full[cur_off:starts[k]].strip()))
                cur, cur_off = [k], starts[k]
            else:
                cur.append(k)
        out.append((cur, full[cur_off:b_off].strip()))
    return out


def _right_lang(text: str, dst: str) -> bool:
    """Модель иногда возвращает оригинал вместо перевода — проверяем алфавит ответа."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return True
    cyr = sum("а" <= ch.lower() <= "я" or ch.lower() == "ё" for ch in letters) / len(letters)
    return cyr > 0.5 if dst in ("ru", "uk") else cyr < 0.2


def _ask_batch(src: str, dst: str, context: str, items: list[str]) -> list[str] | None:
    numbered = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(items))
    # Контекст — после списка и без номера, иначе маленькая модель переводит его вместо пункта 1
    ctx = f"\n\nДля понимания (не переводить): перед пунктом 1 лектор сказал: «{context}»" if context else ""
    keys = ", ".join(f'"{i + 1}": "..."' for i in range(len(items)))
    data = llm.chat_json([
        {"role": "system", "content": (
            f"Ты переводчик расшифровок видеолекций с языка «{_name(src)}» на язык «{_name(dst)}». "
            "Переводишь точно и естественно, как говорил бы лектор, сохраняешь термины, числа и формулы. "
            "Ничего не добавляешь и не пропускаешь. Отвечаешь строго в формате JSON."
        )},
        {"role": "user", "content": (
            f"Переведи на язык «{_name(dst)}» каждый пункт — это идущие подряд предложения из одной лекции.\n\n"
            f"{numbered}{ctx}\n\nВерни JSON {{{keys}}} — перевод каждого пункта под его номером."
        )},
    ], temperature=0.1, num_ctx=4096, timeout=180)
    out = []
    for i in range(len(items)):
        t = data.get(str(i + 1)) if isinstance(data, dict) else None
        if not isinstance(t, str) or not t.strip() or not _right_lang(t, dst):
            return None
        out.append(t.strip())
    return out


def translate_segments(lecture_id: str, should_stop=lambda: False, on_progress=None) -> bool:
    """Переводит ещё не переведённые предложения. False — прервались, потому что ждёт более важная работа.

    Перевод предложения пишется в его первую фразу, у остальных фраз предложения — пустая строка:
    при показе перевода они склеиваются с первой (см. merged)."""
    lec = db.get_lecture(lecture_id)
    src, dst = lec.get("language") or "ru", target_lang(lec.get("language"))
    segs = db.get_segments(lecture_id)
    all_units = units(segs)
    todo = [u for u in all_units if segs[u[0][0]]["text_tr"] is None]
    pos = {u[0][0]: n for n, u in enumerate(all_units)}
    i = 0
    while i < len(todo):
        if should_stop():
            return False
        # Пачка — подряд идущие непереведённые предложения, не длиннее ~1200 знаков
        batch = [todo[i]]
        size = len(todo[i][1])
        while (len(batch) < BATCH and i + len(batch) < len(todo)
               and pos[todo[i + len(batch)][0][0]] == pos[batch[-1][0][0]] + 1 and size < 1200):
            batch.append(todo[i + len(batch)])
            size += len(batch[-1][1])
        texts = [t for _, t in batch]
        prev = pos[batch[0][0][0]] - 1
        context = all_units[prev][1] if prev >= 0 else ""
        res = None
        try:
            res = _ask_batch(src, dst, context, texts)
        except ValueError:  # модель вернула не JSON
            res = None
        if res is None:
            # Модель сбилась с нумерацией или ответила не на том языке — по одному предложению, до двух попыток
            res = []
            for n, t in enumerate(texts):
                one = None
                for _ in range(2):
                    try:
                        one = _ask_batch(src, dst, texts[n - 1] if n else context, [t])
                    except ValueError:
                        one = None
                    if one:
                        break
                res.append(one[0] if one else t)
        rows = []
        for (u, _), t in zip(batch, res):
            rows.append((t, lecture_id, segs[u[0]]["idx"]))
            rows += [("", lecture_id, segs[k]["idx"]) for k in u[1:]]
        db.executemany("UPDATE segments SET text_tr = ? WHERE lecture_id = ? AND idx = ?", rows)
        i += len(batch)
        if on_progress:
            on_progress(i / len(todo))
    return True


def merged(segs: list[dict]) -> list[dict]:
    """Фразы в переводе: предложение — одна запись от начала первой фразы до конца последней."""
    out = []
    for s in segs:
        if s.get("text_tr") == "" and out:
            out[-1]["end"] = s["end"]
        else:
            out.append({**s, "text": s.get("text_tr") or s["text"]})
    return out


def translate_titles(lecture_id: str):
    """Заголовки разделов и подразделов — на второй язык лекции (рядом с русскими, не вместо них)."""
    lec = db.get_lecture(lecture_id)
    outline = lec.get("outline") or []
    dst = alt_lang(lec.get("language"))
    titles = []
    for sec in outline:
        titles.append(sec["title"])
        titles += [c["title"] for c in sec.get("children") or []]
    if not titles:
        return
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))
    keys = ", ".join(f'"{i + 1}": "..."' for i in range(len(titles)))
    data = llm.chat_json([
        {"role": "system", "content": f"Ты переводишь заголовки разделов лекции на язык «{_name(dst)}». "
                                      "Коротко и точно, как заголовки. Отвечаешь строго в формате JSON."},
        {"role": "user", "content": f"Лекция «{lec['title']}». Заголовки:\n\n{numbered}\n\n"
                                    f"Верни JSON {{{keys}}} — перевод каждого заголовка под его номером."},
    ], temperature=0.1, num_ctx=4096, timeout=180)
    out = [str(data.get(str(i + 1)) or "").strip() or t for i, t in enumerate(titles)]
    it = iter(out)
    sections = []
    for sec in outline:
        sections.append({"title": next(it), "children": [next(it) for _ in sec.get("children") or []]})
    db.update_lecture(lecture_id, outline_alt={"lang": dst, "sections": sections})
