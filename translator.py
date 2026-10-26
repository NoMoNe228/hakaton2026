import whisper

def get_transcription_array_with_timestamps(video_path: str) -> list[str]:
    print("Загрузка нейросети Whisper...")
    # Модель 'medium' оптимальна по скорости и качеству для двуязычной речи
    model = whisper.load_model("medium")
    
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

# --- Пример использования ---
video_file = "testvid.mp4"
lines = get_transcription_array_with_timestamps(video_file)
