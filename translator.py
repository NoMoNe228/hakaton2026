import whisper
_cached_model = None

def get_transcription_array_with_timestamps(video_path: str) -> list[str]:
    global _cached_model
    
    # ПРОВЕРКА: Если модель еще не загружена в память, загружаем её
    if _cached_model is None:
        print("Модель не найдена в памяти. Загрузка нейросети Whisper...")
        # Используем "small" для скорости или "medium" для максимального качества
        _cached_model = whisper.load_model("small")
        print("Модель успешно загружена и сохранена в кэш!")
    else:
        print("Отлично! Модель уже была загружена ранее, используем её повторно.")
    print("Начало расшифровки...")
    result = model.transcribe(video_path, task="transcribe")
    
    subtitles_array = []
    
    for segment in result['segments']:
        # Получаем точное время старта и конца в секундах
        start = segment['start']
        end = segment['end']
        text = segment['text'].strip()
        
        # Внутренняя функция для перевода секунд в формат ЧЧ:ММ:СС.ммм
        def format_time(seconds: float) -> str:
            hrs = int(seconds // 3600)
            mins = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            msecs = int((seconds - int(seconds)) * 1000)
            return f"{hrs:02d}:{mins:02d}:{secs:02d}.{msecs:03d}"
        
        # Формируем строку с интервалом времени и текстом
        timestamp_str = f"[{format_time(start)} --> {format_time(end)}] {text}"
        subtitles_array.append(timestamp_str)
            
    return subtitles_array
# --- ЭТОТ БЛОК ОБЯЗАТЕЛЬНО ДОЛЖЕН БЫТЬ В САМОМ НИЗУ ФАЙЛА ---
if __name__ == "__main__":
    # Укажите точное имя вашего видеофайла, который лежит в папке hakaton2026
    video_file = "testvid.mp4" 
    
    # 1. Запускаем функцию и сохраняем результат в переменную lines
    lines = get_transcription_array_with_timestamps(video_file)
    
    # 2. Выводим результат в терминал построчно
    print("\n--- Результат расшифровки: ---")
    for line in lines:
        print(line)

