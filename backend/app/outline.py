"""Конспект и структура лекции.

1. Лекция делится на смысловые блоки: там, где соседние куски текста сильнее всего расходятся по смыслу
   (сравниваем их векторы), — граница темы. Блок длиной 2–8 минут.
2. Для каждого блока локальная модель пишет заголовок, главные мысли и ключевые термины — это подразделы.
3. Последним запросом модель группирует подразделы в разделы и пишет общий конспект лекции.
"""
import numpy as np

from . import llm, search
from .textutil import fmt_time, stem, WORD

SYSTEM = (
    "Ты помогаешь студентам: составляешь точные конспекты видеолекций. "
    "Пиши по-русски, даже если лекция на английском. Не выдумывай того, чего нет в тексте. "
    "Отвечай строго в формате JSON."
)


def split_blocks(chunks: list[dict], emb: np.ndarray) -> list[tuple[int, int]]:
    """Делит куски на смысловые блоки. Возвращает пары (первый кусок, последний кусок + 1).

    Длина блока зависит от длины видео: ролик на 5 минут — блоки ~1 мин,
    лекция на 15–20 минут — ~2,5–3 мин, полуторачасовая — ~4,5 мин.
    """
    n = len(chunks)
    if n == 0:
        return []
    total = chunks[-1]["end"] - chunks[0]["start"]
    target = min(270.0, max(60.0, total / 6))
    min_len, max_len = target * 0.5, target * 1.8
    if total < 90 or n < 3:
        return [(0, n)]
    # Насколько различаются по смыслу несколько кусков до границы и после
    w = max(1, min(3, n // 6))
    gap = np.ones(n)
    for i in range(1, n):
        a = emb[max(0, i - w):i].mean(0)
        b = emb[i:i + w].mean(0)
        gap[i] = float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))
    want = max(2, round(total / target))
    cuts = [0]
    for i in np.argsort(gap):  # от самых сильных смен темы
        if i == 0 or len(cuts) >= want:
            continue
        t = chunks[i]["start"]
        if all(abs(t - chunks[c]["start"]) >= min_len for c in cuts) and chunks[-1]["end"] - t >= min_len:
            cuts.append(int(i))
    cuts = sorted(cuts) + [n]
    # Слишком длинные блоки режем пополам
    blocks = []
    for a, b in zip(cuts, cuts[1:]):
        stack = [(a, b)]
        while stack:
            x, y = stack.pop(0)
            if chunks[y - 1]["end"] - chunks[x]["start"] > max_len and y - x >= 2:
                m = (x + y) // 2
                stack[:0] = [(x, m), (m, y)]
            else:
                blocks.append((x, y))
    return blocks


def _block_text(segments, start, end, limit_chars=9000):
    lines, last_mark = [], -999
    for s in segments:
        if s["start"] < start - 0.01 or s["start"] >= end:
            continue
        if s["start"] - last_mark >= 30:
            lines.append(f"[{fmt_time(s['start'])}] {s['text']}")
            last_mark = s["start"]
        else:
            lines[-1] += " " + s["text"]
    text = "\n".join(lines)
    return text[:limit_chars]


def _term_time(term: str, segments, start, end, default=None) -> float:
    """Первое место в блоке, где звучит термин (по основе первого значимого слова)."""
    default = start if default is None else default
    words = [stem(m.group()) for m in WORD.finditer(term)]
    if not words:
        return default
    key = max(words, key=len)
    for s in segments:
        if start - 0.01 <= s["start"] < end and any(stem(m.group()) == key for m in WORD.finditer(s["text"])):
            return s["start"]
    return default


def _place_terms(terms: list[dict], segments: list[dict], same=0.85) -> list[dict]:
    """Убирает дубли («сигмоида» и «сигмоидная функция») и находит момент, где о термине говорят.

    Момент ищем по смыслу среди фраз своего блока: так находится и английская фраза для русского термина.
    Берём самое раннее место, почти такое же близкое, как лучшее, — то есть первое упоминание.
    """
    if not terms:
        return []
    vecs = search.embed([t["term"] for t in terms])
    full = search.embed([f"{t['term']}: {t['definition']}" for t in terms])
    kept = []
    for i, t in enumerate(terms):
        if any(float(vecs[i] @ vecs[j]) >= same for j in kept):
            continue
        kept.append(i)
    out = []
    for i in kept:
        t = terms[i]
        a, b = t.pop("block")
        t["start"] = _term_time(t["term"], segments, a, b, a - 1)
        if t["start"] == a - 1:
            cand = [s for s in segments if a - 0.01 <= s["start"] < b and s.get("vec") is not None]
            if cand:
                sims = np.array([float(s["vec"] @ full[i]) for s in cand])
                ok = np.flatnonzero(sims >= sims.max() - 0.03)
                t["start"] = cand[int(ok[0])]["start"]
            else:
                t["start"] = a
        out.append(t)
    return sorted(out, key=lambda t: t["start"])


def build(title: str, segments: list[dict], chunks: list[dict], emb: np.ndarray, on_progress=None) -> dict:
    blocks = split_blocks(chunks, emb)
    subs, terms = [], {}
    for k, (a, b) in enumerate(blocks):
        # Куски перекрываются, поэтому блок заканчивается там, где начинается следующий
        start = chunks[a]["start"]
        end = chunks[b]["start"] if b < len(chunks) else chunks[-1]["end"]
        text = _block_text(segments, start, end)
        used = "; ".join(x["title"] for x in subs)
        avoid = f" Не повторяй заголовки предыдущих фрагментов: {used}." if used else ""
        data = llm.chat_json([
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": (
                f"Лекция «{title}». Фрагмент с {fmt_time(start)} по {fmt_time(end)}:\n\n{text}\n\n"
                "Верни JSON вида {\"title\": \"заголовок фрагмента, 3–7 слов\", "
                "\"points\": [\"2–4 главные мысли, по одному предложению\"], "
                "\"terms\": [{\"term\": \"понятие\", \"definition\": \"краткое определение из лекции\"}]}. "
                "Термины — только важные понятия, которые действительно объясняются во фрагменте, не больше 4."
                + avoid
            )},
        ], num_ctx=6144)
        sub = {
            "title": str(data.get("title") or f"Фрагмент {k + 1}").strip(),
            "points": [str(p).strip() for p in (data.get("points") or []) if str(p).strip()][:5],
            "start": start,
            "end": end,
        }
        subs.append(sub)
        for t in data.get("terms") or []:
            if not isinstance(t, dict) or not t.get("term"):
                continue
            name = str(t["term"]).strip()
            key = name.lower()
            if key not in terms:
                terms[key] = {"term": name, "definition": str(t.get("definition") or "").strip(),
                              "block": (start, end)}
        if on_progress:
            on_progress((k + 1) / (len(blocks) + 1))

    term_list = _place_terms(list(terms.values()), segments)

    listing = "\n".join(
        f"{i}. [{fmt_time(s['start'])}] {s['title']}: " + " ".join(s["points"]) for i, s in enumerate(subs)
    )
    data = llm.chat_json([
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": (
            f"Лекция «{title}». Её фрагменты по порядку (номер, время, заголовок, главные мысли):\n\n{listing}\n\n"
            "Верни JSON вида {\"summary\": \"конспект всей лекции, 5–8 предложений\", "
            "\"key_points\": [\"5–8 главных выводов лекции\"], "
            "\"sections\": [{\"title\": \"название раздела\", \"from\": номер первого фрагмента}]}. "
            "Разделы — 2–7 крупных частей лекции, каждая объединяет подряд идущие фрагменты; "
            "первый раздел начинается с фрагмента 0."
        )},
    ], num_ctx=8192)

    # Разделы: по номерам первых фрагментов, остальное достраиваем сами
    starts = {}
    for s in data.get("sections") or []:
        try:
            i = int(s.get("from"))
        except (TypeError, ValueError, AttributeError):
            continue
        if 0 <= i < len(subs) and i not in starts:
            starts[i] = str(s.get("title") or "").strip()
    if 0 not in starts:
        starts[0] = subs[0]["title"] if len(subs) == 1 else "Введение"
    if len(subs) <= 4:
        # Короткая лекция: каждый смысловой блок — отдельный раздел, группировать нечего
        starts = {i: s["title"] for i, s in enumerate(subs)}
    elif len(starts) == 1:
        # Модель свалила всё в один раздел — делим сами примерно по три блока
        starts = {i: subs[i]["title"] for i in range(0, len(subs), 3)}
    order = sorted(starts)
    sections = []
    for a, b in zip(order, order[1:] + [len(subs)]):
        part = subs[a:b]
        sections.append({"title": starts[a] or part[0]["title"], "start": part[0]["start"],
                         "end": part[-1]["end"], "children": part})
    if on_progress:
        on_progress(1.0)
    return {
        "summary": {"text": str(data.get("summary") or "").strip(),
                    "key_points": [str(p).strip() for p in (data.get("key_points") or []) if str(p).strip()]},
        "outline": sections,
        "terms": term_list,
    }
