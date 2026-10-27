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
    the a an and or of to in on for with is are was were be been it this that these those as at by from what which
    who how why when where do does did not no so if then than there here we you they he she i me my our your their
    its about into over can could would should will just also very really like okay ok um uh""".split()
)


def stem(word: str) -> str:
    w = word.lower().replace("ё", "е")
    return _ru.stemWord(w) if _CYR.search(w) else _en.stemWord(w)


def tokens(text: str) -> list[str]:
    return [stem(m.group()) for m in WORD.finditer(text) if m.group().lower() not in STOP]


def highlight_spans(text: str, stems: set[str]) -> list[list[int]]:
    """Позиции слов текста, совпавших с запросом по основе слова."""
    if not stems:
        return []
    return [
        [m.start(), m.end()]
        for m in WORD.finditer(text)
        if m.group().lower() not in STOP and stem(m.group()) in stems
    ]


def fmt_time(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
