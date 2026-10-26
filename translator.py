import whisper

# Глобальная переменная для кэширования модели в памяти
_cached_model = None

def get_transcription_array_with_timestamps(video_path: str) -> list[dict]:
    global _cached_model
    
    # Проверка: если модель не загружена, загружаем один раз
    if _cached_model is None:
        print("Загрузка нейросети Whisper...")
        _cached_model = whisper.load_model("small")
        print("Модель успешно загружена!")
    
    print("Начало расшифровки...")
    result = _cached_model.transcribe(video_path, task="transcribe", language="ru")
    
    subtitles_array = []
    
    for segment in result['segments']:
        # Формируем структуру словаря с чистыми float числами
        segment_data = {
            "start": float(segment['start']),
            "end": float(segment['end']),
            "text": segment['text'].strip()
        }
        subtitles_array.append(segment_data)
            
    return subtitles_array

# Пример проверки в терминале
if __name__ == "__main__":
    video_file = "testvid.mp4" 
    
    # Вызов функции
    lines = get_transcription_array_with_timestamps(video_file)
    
    # Вывод структуры в консоль
    print("\n--- Результат расшифровки (Как на скриншоте) ---")
    import json
    # json.dumps превратит массив в красивый текст, аналогичный вашему скриншоту
    print(json.dumps(lines, ensure_ascii=False, indent=4))
