import requests
import json
import re

MODEL_NAME = "qwen2.5:1.5b"
URL = "http://localhost:11434/api/generate"

# Наш тестовый текст
LECTURE_TEXT = """
Итак, сегодня мы поговорим про законы Ньютона. Первый закон, или закон инерции, гласит, что существуют такие системы отсчета, в которых тело сохраняет состояние покоя или равномерного прямолинейного движения, если на него не действуют силы или их действие скомпенсировано. Такие системы называются инерциальными. Например, если мы едем в поезде и поезд резко тормозит, мы наклоняемся вперед, потому что наше тело продолжает двигаться по инерции. Второй закон Ньютона связывает силу, массу и ускорение. Формула выглядит как F равно m умножить на a. То есть ускорение тела прямо пропорционально приложенной силе и обратно пропорционально его массе. Это значит, что чем тяжелее объект, тем больше силы нужно приложить, чтобы его разогнать с той же скоростью. Третий закон говорит о том, что сила действия равна силе противодействия. Когда мы отталкиваемся от земли, земля отталкивает нас обратно. На этом принципе работает реактивное движение, которое мы рассмотрим подробнее на следующей лекции.
"""

# 1. ФУНКЦИЯ-СТРАХОВКА (Fallback) - если нейросеть не справилась
def fallback_structure(segments_count=3, total_time=330):
    step = total_time / segments_count
    result = []
    for i in range(segments_count):
        result.append({
            "title": f"Часть {i+1}",
            "start": int(i * step),
            "end": int((i + 1) * step)
        })
    return result

# 2. ГЛАВНАЯ ФУНКЦИЯ
def get_structure(text):
    prompt = f"""
    Ты — ассистент, структурирующий лекцию. Разбей текст на 3 логических раздела по смыслу.
    Верни ответ СТРОГО в формате JSON-массива без лишнего текста.
    Не копируй предложения из текста, придумай короткие названия (до 5 слов).
    Пример: [{{"title": "Введение", "start": 0, "end": 100}}, {{"title": "Основная часть", "start": 100, "end": 200}}]
    
    Текст:
    {text}
    """
    
    print("Отправляем запрос к нейросети (ждем максимум 30 секунд)...")
    try:
        # timeout=30 — это наш спасательный круг. Если модель зависнет, скрипт не умрет.
        response = requests.post(URL, json={
            "model": MODEL_NAME,
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }, timeout=30)
        
        raw_response = response.json()["response"]
        print(f"Сырой ответ от модели: {raw_response[:200]}...")
        
        # Убираем возможные markdown-кавычки
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_response.strip(), flags=re.MULTILINE)
        
        # Пытаемся найти JSON внутри текста
        match = re.search(r"(\[.*\]|\{.*\})", cleaned, re.DOTALL)
        if not match:
            raise ValueError("Не нашли JSON в ответе")
            
        data = json.loads(match.group(1))
        
        # Если модель вернула объект {"0": {...}, "1": {...}} — превращаем его в список
        if isinstance(data, dict):
            data = list(data.values())
            
        # Проверяем, что это реально список и в нем есть нужные поля
        if not isinstance(data, list) or len(data) < 2:
            raise ValueError("Модель вернула мало разделов или не список")
            
        for item in data:
            if "title" not in item or "start" not in item or "end" not in item:
                raise ValueError("В ответе не хватает полей title, start или end")
                
        print("✅ Нейросеть отлично справилась! JSON валидный.")
        return data

    except requests.exceptions.Timeout:
        print("❌ Модель зависла (прошло 30 секунд). Включаем страховку (Fallback).")
        return fallback_structure()
    except Exception as e:
        print(f"❌ Модель выдала ошибку: {e}. Включаем страховку (Fallback).")
        return fallback_structure()

# Запускаем тест
if __name__ == "__main__":
    result = get_structure(LECTURE_TEXT)
    print("\n--- ИТОГОВАЯ СТРУКТУРА ---")
    print(json.dumps(result, ensure_ascii=False, indent=2))