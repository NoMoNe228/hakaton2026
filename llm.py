import json
import re
import time
import logging
import requests
import numpy as np
from typing import List, Dict, Any

# Настройка логирования (чтобы видеть, что происходит)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- НАСТРОЙКИ ---
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5:1.5b"  # Если найдешь ключ OpenAI, можно переключить на него
MAX_TIMEOUT = 60  # Ждем ответа от нейросети максимум 60 секунд

# ==========================================
# 1. БАЗОВЫЙ КЛИЕНТ (С ЗАЩИТОЙ ОТ ЗАВИСАНИЙ)
# ==========================================
def chat(prompt: str, json_mode: bool = False) -> str:
    """Отправляет запрос в Ollama. Делает 2 попытки при ошибке."""
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2}
    }
    if json_mode:
        payload["format"] = "json"
        
    for attempt in range(2): # 2 попытки
        try:
            logging.info(f"Отправка запроса в LLM (попытка {attempt+1})...")
            response = requests.post(OLLAMA_URL, json=payload, timeout=MAX_TIMEOUT)
            response.raise_for_status()
            return response.json()["response"]
        except requests.exceptions.Timeout:
            logging.warning(f"Таймаут LLM. Попытка {attempt+1} провалена.")
            if attempt == 1: raise
            time.sleep(2)
        except Exception as e:
            logging.error(f"Ошибка LLM: {e}")
            if attempt == 1: raise
            time.sleep(2)

# ==========================================
# 2. ГЕНЕРАЦИЯ СТРУКТУРЫ (JSON + FALLBACK)
# ==========================================
def fallback_structure(segments: List[Dict], n_parts: int = 4) -> List[Dict]:
    """Страховка: если LLM не смогла, делим лекцию на равные части по времени."""
    if not segments: return []
    total_end = segments[-1]["end"]
    step = total_end / n_parts
    result = []
    for i in range(n_parts):
        result.append({
            "title": f"Раздел {i+1}",
            "start": round(i * step, 1),
            "end": round((i + 1) * step, 1)
        })
    return result

def build_structure(segments: List[Dict]) -> List[Dict]:
    """Просит LLM сделать структуру. Если не выходит — включает страховку."""
    if not segments: return []
    
    # Для промпта склеиваем текст, чтобы не отправить слишком много данных
    text_for_prompt = " ".join([s["text"] for s in segments])[:8000] 
    
    prompt = f"""
    Разбей этот текст лекции на 3-5 логических разделов.
    Верни ответ СТРОГО в формате JSON-массива. Пример: [{{"title": "Название", "start": 0, "end": 10}}]
    Текст:
    {text_for_prompt}
    """
    try:
        raw = chat(prompt, json_mode=True)
        
        # Жесткая очистка JSON от мусора
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
        match = re.search(r"(\[.*\]|\{.*\})", cleaned, re.DOTALL)
        if not match: raise ValueError("Не нашли JSON")
        
        data = json.loads(match.group(1))
        
        # Чиним ответ, если он не в виде списка
        if isinstance(data, dict) and "title" in data:
            data = [data]
        elif isinstance(data, dict) and "sections" in data:
            data = data["sections"]
        elif isinstance(data, dict):
            data = list(data.values())
            
        if not isinstance(data, list) or len(data) < 2:
            raise ValueError("Мало разделов")
            
        # Приводим таймкоды к float, на случай если LLM вернула строки
        for item in data:
            item["start"] = float(item["start"])
            item["end"] = float(item["end"])
            
        return data
    except Exception as e:
        logging.error(f"LLM не справилась со структурой ({e}). Включаю Fallback.")
        return fallback_structure(segments)

# ==========================================
# 3. ГЕНЕРАЦИЯ КОНСПЕКТА (MAP-REDUCE)
# ==========================================
def summarize(segments: List[Dict]) -> str:
    """Делает конспект длинной лекции, разбивая ее на куски."""
    if not segments: return ""
    
    # 1. Склеиваем сегменты в крупные блоки (по ~2000 символов)
    blocks = []
    current_block = ""
    for seg in segments:
        if len(current_block) + len(seg["text"]) > 2000 and current_block:
            blocks.append(current_block)
            current_block = ""
        current_block += " " + seg["text"]
    if current_block:
        blocks.append(current_block)
        
    # Если лекция короткая (1 блок) — делаем конспект сразу
    if len(blocks) == 1:
        return chat(f"Сделай краткий конспект этого текста (3-5 предложений):\n{blocks[0]}")
        
    # Если длинная — делаем резюме каждого куска (MAP), затем склеиваем
    logging.info(f"Длинная лекция ({len(blocks)} блоков). Запускаю Map-Reduce.")
    mini_summaries = []
    for b in blocks:
        try:
            summary = chat(f"Сделай краткое резюме этого куска лекции (2-3 предложения):\n{b}")
            mini_summaries.append(summary)
        except Exception:
            mini_summaries.append(b[:200] + "...") # Страховка
            
    # REDUCE: просим нейросеть объединить все резюме
    combined = "\n\n".join(mini_summaries)
    final_prompt = f"Вот краткие резюме кусков одной лекции. Сделай из них единый красивый конспект (10 предложений):\n{combined}"
    return chat(final_prompt)

# ==========================================
# 4. ОТВЕТЫ НА ВОПРОСЫ (RAG)
# ==========================================
def ask(question: str, segments: List[Dict], emb_matrix: np.ndarray, embed_fn) -> Dict:
    """Ищет ответ на вопрос в тексте лекции через эмбеддинги."""
    if not question or not segments:
        return {"answer": "Не удалось найти ответ.", "sources": []}
        
    # 1. Векторизуем вопрос (используем функцию от бэкендера)
    q_emb = embed_fn([question])[0]
    
    # 2. Ищем самые похожие куски (косинусное расстояние)
    scores = emb_matrix @ q_emb
    top_indices = np.argsort(scores)[::-1][:3] # берем ТОП-3 куска
    
    # 3. Формируем контекст
    context = ""
    sources = []
    for idx in top_indices:
        seg = segments[idx]
        context += f"[{seg['start']:.0f} сек]: {seg['text']}\n"
        sources.append({"start": seg['start'], "text": seg['text'][:150]})
        
    # 4. Просим LLM ответить
    prompt = f"""
    Ответь на вопрос пользователя, используя ТОЛЬКО этот текст:
    {context}
    
    Вопрос: {question}
    Если ответа нет в тексте, напиши "В лекции это не объясняется".
    """
    try:
        answer = chat(prompt)
    except Exception:
        answer = "Ошибка генерации ответа. Вот найденные фрагменты:\n" + context
        
    return {"answer": answer, "sources": sources}

