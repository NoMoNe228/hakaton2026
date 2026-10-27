"""База знаний курса: все понятия из всех лекций в одном месте.

Понятия берутся из терминов, которые локальная модель выделила при составлении конспекта.
Одно и то же понятие из разных лекций склеивается: сначала по основам слов
(«сигмоида» и «сигмоиды»), затем по смыслу названий («нейросеть» и «нейронная сеть»).
"""
import json
import threading

import numpy as np
from fastapi import APIRouter

from . import db, search
from .textutil import WORD, stem

router = APIRouter()
SAME = 0.86  # близость названий, начиная с которой это одно понятие
RELATED = 0.62  # близость, начиная с которой понятия считаются связанными

_cache = {"key": None, "data": None}
_lock = threading.Lock()


def _word_key(name: str) -> str:
    return " ".join(stem(m.group()) for m in WORD.finditer(name))


def _sort_key(name: str):
    n = name.lower().replace("ё", "е")
    # Сначала русские понятия, затем латиница и прочее
    return (0 if "а" <= n[:1] <= "я" else 1, n)


def _letter(name: str) -> str:
    ch = name[:1].upper().replace("Ё", "Е")
    return ch if ch.isalpha() else "#"


def _build(rows) -> dict:
    items = []
    for r in rows:
        for t in json.loads(r["terms"]) or []:
            name = str(t.get("term") or "").strip()
            if name:
                items.append({"term": name, "definition": str(t.get("definition") or "").strip(),
                              "lecture_id": r["id"], "lecture_title": r["title"], "start": t.get("start") or 0})
    n = len(items)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        parent[find(a)] = find(b)

    first = {}
    for i, it in enumerate(items):
        key = _word_key(it["term"])
        if key in first:
            union(i, first[key])
        else:
            first[key] = i

    semantic = search.models_ready() and n > 1
    vecs = search.embed([it["term"] for it in items]) if semantic else None
    if semantic:
        sims = vecs @ vecs.T
        for i, j in zip(*np.nonzero(np.triu(sims, 1) >= SAME)):
            union(int(i), int(j))

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    concepts = []
    for members in groups.values():
        names = [items[i]["term"] for i in members]
        # Название — самое частое, при равенстве — самое короткое
        name = min(set(names), key=lambda x: (-names.count(x), len(x)))
        mentions = sorted((items[i] for i in members), key=lambda m: (m["lecture_title"], m["start"]))
        # Одна лекция — одно упоминание (самое раннее)
        seen, uniq = set(), []
        for m in mentions:
            if m["lecture_id"] not in seen:
                seen.add(m["lecture_id"])
                uniq.append({k: m[k] for k in ("lecture_id", "lecture_title", "definition", "start")})
        definition = max((m["definition"] for m in uniq), key=len, default="")
        concepts.append({"name": name, "letter": _letter(name), "definition": definition,
                         "mentions": uniq, "lectures": len(uniq), "related": [], "_members": members})

    if semantic and len(concepts) > 1:
        cv = np.stack([vecs[c["_members"]].mean(0) for c in concepts])
        cv /= np.linalg.norm(cv, axis=1, keepdims=True) + 1e-9
        cs = cv @ cv.T
        np.fill_diagonal(cs, -1)
        for i, c in enumerate(concepts):
            best = [j for j in np.argsort(-cs[i])[:4] if cs[i, j] >= RELATED]
            c["related"] = [concepts[j]["name"] for j in best]
    for c in concepts:
        c.pop("_members")
    concepts.sort(key=lambda c: _sort_key(c["name"]))
    return {"concepts": concepts, "lectures": len(rows), "semantic": bool(semantic)}


@router.get("/api/knowledge")
def knowledge():
    rows = db.query(
        "SELECT id, title, terms FROM lectures WHERE terms IS NOT NULL AND status IN ('summarizing', 'ready')"
        " ORDER BY created_at"
    )
    # Пересчитываем, только если изменились лекции или их термины (или загрузились модели)
    key = (tuple((r["id"], r["title"], len(r["terms"])) for r in rows), search.models_ready())
    with _lock:
        if _cache["key"] != key:
            _cache["data"], _cache["key"] = _build(rows), key
        return _cache["data"]
