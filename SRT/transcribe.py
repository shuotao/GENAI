import os
import subprocess
import json
import requests
from datetime import timedelta
import shutil
import time

# ================= 設定區 =================
INPUT_FOLDER = "."       # 影音檔案資料夾 (目前專案目錄)
OUTPUT_FOLDER = "."      # 輸出的 SRT 資料夾 (目前專案目錄)
CHUNK_DURATION = 600     # 每個切片的長度（秒）。600秒 = 10分鐘，避免 Whisper 遺漏長語音段落
# ==========================================

def format_time(seconds):
    """將秒數轉換為 SRT 標準格式 (HH:MM:SS,mmm)"""
    td = timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    # 毫秒部分
    milliseconds = int((seconds - total_seconds) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"

def extract_and_split_audio(input_file, temp_dir):
    """使用 FFmpeg 抽取音訊並依固定時間切片"""
    print(f"🔄 正在處理/切片檔案: {os.path.basename(input_file)}")
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    output_pattern = os.path.join(temp_dir, f"{base_name}_chunk_%03d.mp3")
    
    # FFmpeg 參數：
    command = [
        "ffmpeg", "-y", "-i", input_file,
        "-vn", "-ar", "16000", "-ac", "1", "-b:a", "64k",
        "-f", "segment", "-segment_time", str(CHUNK_DURATION),
        output_pattern
    ]
    
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    chunks = sorted([os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if f.startswith(f"{base_name}_chunk_")])
    return chunks

def transcribe_with_groq(chunk_path, api_key, custom_context):
    """直接發送 HTTP POST 請求給 Groq API，不透過官方 SDK"""
    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    headers = {
        "Authorization": f"Bearer {api_key}"
    }
    
    # Whisper 的 prompt 用來充當「先驗詞彙」或「文風參考」，不能下達指令。
    # 增加「簡報」等高頻會議用詞，大幅減少因為同音字產生的錯誤 (如：剪報 -> 簡報)
    base_prompt = "這是一段關於技術開發與會議簡報內容的繁體中文錄音。"
    final_prompt = f"{base_prompt} 內容包含：{custom_context}。" if custom_context else base_prompt

    data = {
        "model": "whisper-large-v3",
        "prompt": final_prompt,
        "response_format": "verbose_json",
        "language": "zh",
        "temperature": "0.0"
    }

    try:
        with open(chunk_path, "rb") as f:
            files = {
                "file": (os.path.basename(chunk_path), f, "audio/mpeg")
            }
            response = requests.post(url, headers=headers, data=data, files=files)
            
            if response.status_code != 200:
                print(f"❌ Groq API 錯誤: {response.text}")
                return None
                
            return response.json()
    except Exception as e:
        print(f"❌ 呼叫過程發生錯誤: {e}")
        return None

def process_file(file_path, api_key, custom_context):
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    srt_output_path = os.path.join(OUTPUT_FOLDER, f"{base_name}.srt")
    
    temp_dir = os.path.join(OUTPUT_FOLDER, f"temp_{base_name}")
    os.makedirs(temp_dir, exist_ok=True)
    
    chunks = extract_and_split_audio(file_path, temp_dir)
    print(f"✅ 成功切分為 {len(chunks)} 個音檔片段。準備呼叫 Groq API...")

    global_srt_index = 1
    
    with open(srt_output_path, "w", encoding="utf-8") as srt_file:
        for i, chunk_path in enumerate(chunks):
            print(f"🚀 正在辨識片段 {i+1}/{len(chunks)} ...")
            time_offset = i * CHUNK_DURATION
            result = transcribe_with_groq(chunk_path, api_key, custom_context)
            if result:
                segments = result.get("segments", [])
                for seg in segments:
                    text = seg.get("text", "").strip()
                    if not text:
                        continue
                    actual_start = seg["start"] + time_offset
                    actual_end = seg["end"] + time_offset
                    srt_file.write(f"{global_srt_index}\n")
                    srt_file.write(f"{format_time(actual_start)} --> {format_time(actual_end)}\n")
                    srt_file.write(f"{text}\n\n")
                    global_srt_index += 1
            os.remove(chunk_path)
            
    shutil.rmtree(temp_dir)
    print(f"🎉 初步逐字稿已儲存至: {srt_output_path}")
    
    # 呼叫 QA/QC 作業
    print("🧹 準備執行 QA/QC 自動修正與重新排序...")
    subprocess.run(["python3", "qaqc_srt.py", srt_output_path])

def main():
    print("==================================================")
    print("    🚀 Groq 極速逐字稿工具 (SRT 來源檔產出)    ")
    print("==================================================")
    
    groq_api_key = input("請輸入你的 Groq API Key: ").strip()
    if not groq_api_key:
        print("❌ 必須提供 API Key 才能執行。")
        return

    supported_formats = ('.mp4', '.mp3', '.wav', '.m4a', '.mov', '.mkv', '.mpeg')
    files = [f for f in os.listdir(INPUT_FOLDER) if f.lower().endswith(supported_formats)]
    
    if not files:
        print(f"📭 沒有在 {INPUT_FOLDER} 資料夾中找到支援的影音檔案。")
        return
        
    context_path = os.path.join(INPUT_FOLDER, "context.txt")
    custom_context = ""
    if os.path.exists(context_path):
        with open(context_path, "r", encoding="utf-8") as f:
            custom_context = f.read().replace('\n', ', ').strip()
        print(f"🧠 已載入背景詞庫，將注入至 Whisper 提升辨識率！")
    
    print(f"📦 找到 {len(files)} 個待處理檔案。")
    start_time = time.time()
    for file_name in files:
        if file_name.lower().endswith('.txt'):
            continue
        file_path = os.path.join(INPUT_FOLDER, file_name)
        process_file(file_path, groq_api_key, custom_context)
        
    end_time = time.time()
    elapsed_time = end_time - start_time
    print("==================================================")
    print(f"⏱️ 本次測試檔案轉 SRT 總執行時間: {elapsed_time:.2f} 秒")
    print("==================================================")

if __name__ == "__main__":
    main()
