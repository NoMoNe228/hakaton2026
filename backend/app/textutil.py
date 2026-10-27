"""Работа с текстом: слова, основы слов (для поиска по словам), формат времени."""
import re

import snowballstemmer

WORD = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+(?:[-'][0-9A-Za-zА-Яа-яЁё]+)*")
_CYR = re.compile(r"[а-яё]")
_ru = snowballstemmer.stemmer("russian")
_en = snowballstemmer.stemmer("english")

STOP = set(
    """и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее мне было вот от меня
    еще нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до вас нибудь опять уж вам ведь там
    потом себя ничего ей может они тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего раз тоже себе
    под будет ж тогда кто этот того потому этого какой совсем ним здесь этом один почти мой тем чтобы нее сейчас были
    куда зачем всех никогда можно при наконец два об другой хоть после над больше тот через эти нас про всего них
    какая много разве три эту моя впрочем хорошо свою этой перед иногда лучше чуть том нельзя такой им более всегда
    конечно всю между это вот ещё так значит как бы то есть
    такое такая такие таким такими такого таких такую такому какое какие каким какими какого каких какую
    эта эти этих этим этими этому всё весь вся всем всеми свой своё своя свои своих своим своей мой моё мои моих
    который которая которое которые которых которым которой также либо вообще просто очень например давайте
    собственно скажем
    the a an and or of to in on for with is are was were be been it this that these those as at by from what which
    who how why when where do does did not no so if then than there here we you they he she i me my our your their
    its about into over can could would should will just also very really like okay ok um uh
    what's it's that's let's i'm don't gonna""".split()
)


def stem(word: str) -> str:
    w = word.lower().replace("ё", "е")
    return _ru.stemWord(w) if _CYR.search(w) else _en.stemWord(w)


# Самые общие слова языка: есть почти в любом фрагменте и ничего не говорят о теме.
# По ним не ищем и их не подсвечиваем («как работает планировщик» — ищем «планировщик», а не «работает»);
# поиск по смыслу их по-прежнему учитывает. Сравниваем по основе, чтобы отсечь все формы слова.
GENERIC = {stem(w) for w in """
    работать работает работают работал работа делать делает сделать говорить говорит сказать знать знает
    хотеть хочу видеть смотреть думать понимать понять взять брать дать давать идти пойти стать иметь
    получить получать использовать используется нужно нужен должен мочь может можем время человек люди
    вещь дело случай вопрос место часть пример слово образ способ момент первый второй новый большой
    разный каждый любой самый целый простой определенный некоторый следующий
    work works working make makes use used using get gets thing things way time example want know see""".split()}


def _skip(word: str) -> bool:
    return word.lower() in STOP or stem(word) in GENERIC


def tokens(text: str) -> list[str]:
    return [stem(m.group()) for m in WORD.finditer(text) if not _skip(m.group())]


# ---------- Слова на другом алфавите: «виндовс» → Windows, «линукс» → Linux ----------
# Whisper пишет названия так, как их принято писать (Windows), а спрашивают часто как слышат (виндовс).
# Сравниваем слова по звучанию: оба переводятся в латиницу и упрощаются одинаково.

_RU_LAT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                   ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "i", "k", "l", "m", "n", "o", "p", "r",
                    "s", "t", "u", "f", "h", "ts", "ch", "sh", "sch", "", "i", "", "e", "iu", "ia"]))
_SOUND = [("sch", "sh"), ("tch", "ch"), ("ph", "f"), ("th", "t"), ("ck", "k"), ("j", "dzh"), ("x", "ks"),
          ("w", "v"), ("q", "k"), ("c", "k"), ("y", "i")]


def is_cyrillic(word: str) -> bool:
    return bool(_CYR.search(word.lower()))


def sound_key(word: str) -> str:
    """Как слово звучит, латиницей: «виндовс» и «Windows» дают одно и то же — vindovs."""
    w = word.lower().replace("ё", "е")
    if _CYR.search(w):
        w = "".join(_RU_LAT.get(c, c) for c in w)
    for a, b in _SOUND:
        w = w.replace(a, b)
    return re.sub(r"(.)+", r"", w)


def distance(a: str, b: str, limit: int) -> int:
    """Число правок между строками (Левенштейн); больше limit — не считаем до конца."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > limit:
            return limit + 1
        prev = cur
    return prev[-1]


def highlight_spans(text: str, stems: set[str]) -> list[list[int]]:
    """Позиции слов текста, совпавших с запросом по основе слова."""
    if not stems:
        return []
    return [
        [m.start(), m.end()]
        for m in WORD.finditer(text)
        if not _skip(m.group()) and stem(m.group()) in stems
    ]


def fmt_time(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
