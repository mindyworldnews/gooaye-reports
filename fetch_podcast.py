"""
fetch_podcast.py
從 Apple Podcasts RSS 抓取股癌最新集數，下載音檔
"""

import os
import re
import json
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

# 股癌 Apple Podcasts ID
PODCAST_ID = "1500839292"
# 直接使用已知的 RSS URL（避免每次都查 iTunes API）
KNOWN_RSS_URL = "https://feeds.soundon.fm/podcasts/954689a5-3096-43a4-a80b-7810b219cef3.xml"
INPUT_DIR = Path(__file__).parent / "input"
STATE_FILE = Path(__file__).parent / "output" / "downloaded.json"

# 只抓這個日期之後的集數
FETCH_SINCE = datetime(2026, 3, 14, tzinfo=timezone.utc)
# 音檔保留天數（超過後自動刪除，只保留報告）
AUDIO_KEEP_DAYS = 90


def get_rss_url() -> str:
    """取得 RSS feed URL（優先用已知 URL，若失效再查 iTunes API）"""
    # 先確認已知 URL 是否有效
    try:
        req = urllib.request.Request(KNOWN_RSS_URL, method="HEAD")
        with urllib.request.urlopen(req, timeout=10):
            return KNOWN_RSS_URL
    except Exception:
        pass

    # fallback：查 iTunes API
    api_url = f"https://itunes.apple.com/lookup?id={PODCAST_ID}&entity=podcast"
    with urllib.request.urlopen(api_url, timeout=15) as resp:
        data = json.loads(resp.read())
    results = data.get("results", [])
    for r in results:
        if r.get("feedUrl"):
            return r["feedUrl"]
    raise ValueError("找不到股癌 Podcast RSS URL")


def parse_episodes(rss_url: str, limit: int = 5) -> list[dict]:
    """解析 RSS，回傳最新 N 集的資訊"""
    req = urllib.request.Request(
        rss_url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        content = resp.read()
    # ET.fromstring 直接回傳 root Element
    root_elem = ET.fromstring(content)
    if root_elem.tag == "rss":
        root = root_elem.find("channel")
    else:
        root = root_elem

    episodes = []
    for item in root.findall("item"):
        title = item.findtext("title", "").strip()
        pub_date_str = item.findtext("pubDate", "").strip()
        enclosure = item.find("enclosure")

        if enclosure is None:
            continue

        audio_url = enclosure.get("url", "")
        if not audio_url:
            continue

        # 解析發布日期（相容 GMT 與 +0000 兩種格式）
        pub_date = None
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S GMT"):
            try:
                parsed = datetime.strptime(pub_date_str, fmt)
                pub_date = parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
                break
            except ValueError:
                continue

        # 只收 FETCH_SINCE 之後的集數
        if pub_date and pub_date < FETCH_SINCE:
            break  # RSS 按時間倒序，遇到舊的直接停止

        episodes.append({
            "title": title,
            "pub_date": pub_date.isoformat() if pub_date else pub_date_str,
            "pub_date_dt": pub_date,
            "audio_url": audio_url,
        })

        if len(episodes) >= limit:
            break

    return episodes


def load_downloaded() -> set[str]:
    """載入已下載紀錄"""
    if STATE_FILE.exists():
        with open(STATE_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_downloaded(downloaded: set[str]):
    """儲存已下載紀錄"""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(downloaded), f, ensure_ascii=False, indent=2)


def sanitize_filename(title: str) -> str:
    """把標題轉成合法檔名"""
    return re.sub(r'[\\/:*?"<>|]', "_", title)[:80]


def download_episode(episode: dict) -> Path | None:
    """下載單集音檔，回傳本地路徑；若已下載則跳過"""
    downloaded = load_downloaded()
    audio_url = episode["audio_url"]

    if audio_url in downloaded:
        existing = INPUT_DIR / (sanitize_filename(episode["title"]) + ".mp3")
        if existing.exists():
            print(f"  [跳過] 已下載：{episode['title']}")
            return existing
        # 記錄有但檔案不見了，重新下載
        downloaded.discard(audio_url)

    filename = sanitize_filename(episode["title"]) + ".mp3"
    out_path = INPUT_DIR / filename
    INPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"  [下載] {episode['title']}")
    print(f"         URL: {audio_url[:80]}...")

    try:
        # 加 User-Agent 避免被擋
        req = urllib.request.Request(
            audio_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; PodcastFetcher/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp, open(out_path, "wb") as f:
            total = 0
            while chunk := resp.read(65536):
                f.write(chunk)
                total += len(chunk)
            print(f"         完成，大小：{total / 1024 / 1024:.1f} MB")

        downloaded.add(audio_url)
        save_downloaded(downloaded)
        return out_path

    except Exception as e:
        print(f"  [錯誤] 下載失敗：{e}")
        if out_path.exists():
            out_path.unlink()
        return None


def cleanup_old_audio():
    """
    刪除超過 AUDIO_KEEP_DAYS 天的音檔（報告不刪）
    """
    if not INPUT_DIR.exists():
        return
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=AUDIO_KEEP_DAYS)
    deleted = []
    for mp3 in INPUT_DIR.glob("*.mp3"):
        mtime = datetime.fromtimestamp(mp3.stat().st_mtime, tz=timezone.utc)
        if mtime < cutoff:
            mp3.unlink()
            deleted.append(mp3.name)
    if deleted:
        print(f"[清理] 已刪除 {len(deleted)} 個超過 {AUDIO_KEEP_DAYS} 天的音檔：")
        for name in deleted:
            print(f"       - {name}")


def fetch_latest(limit: int = 30) -> list[dict]:
    """
    抓取 2026-01-01 後的集數（最多 limit 集），下載未下載的音檔。
    回傳：[{"title", "pub_date", "audio_url", "local_path"}, ...]
    """
    cleanup_old_audio()

    print("取得 RSS feed URL...")
    rss_url = get_rss_url()
    print(f"RSS: {rss_url}")

    print(f"\n解析集數（{FETCH_SINCE.date()} 之後，最多 {limit} 集）...")
    episodes = parse_episodes(rss_url, limit=limit)

    results = []
    for ep in episodes:
        print(f"\n集數：{ep['title']}")
        print(f"發布：{ep['pub_date']}")
        local_path = download_episode(ep)
        results.append({**ep, "local_path": str(local_path) if local_path else None})
        time.sleep(1)  # 避免過快請求

    return results


if __name__ == "__main__":
    results = fetch_latest(limit=3)
    print("\n===== 結果 =====")
    for r in results:
        status = "已下載" if r["local_path"] else "已存在/跳過"
        print(f"[{status}] {r['title']}")
