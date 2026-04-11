"""
transcribe.py
用 OpenAI Whisper API 將音檔轉成逐字稿，儲存為 .txt
"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path.home() / ".env")

OUTPUT_DIR = Path(__file__).parent / "output"
TRANSCRIPTS_DIR = OUTPUT_DIR / "transcripts"
STATE_FILE = OUTPUT_DIR / "transcribed.json"


def get_openai_client():
    from openai import OpenAI
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("找不到 OPENAI_API_KEY，請確認 ~/.env 有設定")
    return OpenAI(api_key=api_key)


def load_transcribed() -> dict:
    """載入已轉錄紀錄 {audio_path: transcript_path}"""
    if STATE_FILE.exists():
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_transcribed(record: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)


def transcribe_audio(audio_path: Path) -> Path:
    """
    轉錄單個音檔，回傳逐字稿 .txt 路徑。
    若已轉錄過則直接回傳既有檔案。
    """
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    transcribed = load_transcribed()
    audio_key = str(audio_path)

    # 已轉錄過
    if audio_key in transcribed:
        existing = Path(transcribed[audio_key])
        if existing.exists():
            print(f"  [跳過] 已有逐字稿：{existing.name}")
            return existing

    out_path = TRANSCRIPTS_DIR / (audio_path.stem + ".txt")
    print(f"  [轉錄] {audio_path.name}")
    print(f"         檔案大小：{audio_path.stat().st_size / 1024 / 1024:.1f} MB")

    client = get_openai_client()

    # Whisper API 單檔限制 25MB，大檔需切割
    file_size_mb = audio_path.stat().st_size / 1024 / 1024
    if file_size_mb > 24:
        print(f"         檔案 > 24MB，將分段轉錄...")
        transcript_text = transcribe_large_audio(client, audio_path)
    else:
        with open(audio_path, "rb") as f:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language="zh",
                response_format="text",
            )
        transcript_text = response

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(transcript_text)

    print(f"         完成，字數：{len(transcript_text)} 字")

    transcribed[audio_key] = str(out_path)
    save_transcribed(transcribed)
    return out_path


def transcribe_large_audio(client, audio_path: Path) -> str:
    """
    大型音檔分段轉錄，使用 ffmpeg 切割確保每段從正確的 frame 邊界開始。
    """
    import tempfile
    import subprocess

    CHUNK_SECS = 1200  # 每段 20 分鐘

    # 取得總時長
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
        capture_output=True, text=True
    )
    total_secs = float(probe.stdout.strip())
    n_chunks = int((total_secs + CHUNK_SECS - 1) // CHUNK_SECS)
    print(f"         切成 {n_chunks} 段（每段約 {CHUNK_SECS//60} 分鐘）...")

    all_text = []
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        for i in range(n_chunks):
            start = i * CHUNK_SECS
            chunk_path = tmp_dir / f"chunk_{i:02d}.mp3"
            print(f"         轉錄第 {i+1}/{n_chunks} 段...")

            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(start), "-i", str(audio_path),
                 "-t", str(CHUNK_SECS), "-acodec", "copy", str(chunk_path)],
                capture_output=True, check=True
            )

            with open(chunk_path, "rb") as f:
                response = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    language="zh",
                    response_format="text",
                )
            all_text.append(response)
    finally:
        for f in tmp_dir.glob("*.mp3"):
            f.unlink(missing_ok=True)
        tmp_dir.rmdir()

    return "\n".join(all_text)


def transcribe_episodes(episodes: list[dict]) -> list[dict]:
    """
    批次轉錄，episodes 是 fetch_podcast 的輸出格式。
    回傳加上 transcript_path 欄位的列表。
    """
    results = []
    for ep in episodes:
        local_path = ep.get("local_path")
        if not local_path:
            # 沒有下載新音檔，找現有逐字稿
            print(f"[跳過轉錄] {ep['title']}（無音檔）")
            results.append({**ep, "transcript_path": None})
            continue

        audio_path = Path(local_path)
        if not audio_path.exists():
            print(f"[找不到檔案] {audio_path}")
            results.append({**ep, "transcript_path": None})
            continue

        print(f"\n集數：{ep['title']}")
        transcript_path = transcribe_audio(audio_path)
        results.append({**ep, "transcript_path": str(transcript_path)})

    return results


if __name__ == "__main__":
    # 測試：轉錄 input/ 裡的所有 mp3
    input_dir = Path(__file__).parent / "input"
    mp3_files = list(input_dir.glob("*.mp3"))
    if not mp3_files:
        print("input/ 資料夾沒有 mp3 檔案")
    else:
        for mp3 in mp3_files:
            print(f"\n處理：{mp3.name}")
            transcribe_audio(mp3)
