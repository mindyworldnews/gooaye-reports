"""
main.py
股癌 Podcast 分析工具 - 主程式

用法：
  python main.py              # 抓取最新 3 集並分析
  python main.py --limit 5    # 抓取最新 5 集
  python main.py --skip-download  # 跳過下載，只分析已有音檔
  python main.py --skip-transcribe  # 跳過轉錄，只分析已有逐字稿
  python main.py --transcript output/transcripts/xxx.txt  # 分析單一逐字稿
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import argparse
import json
from pathlib import Path
from datetime import datetime


OUTPUT_DIR = Path(__file__).parent / "output"
REPORTS_DIR = Path(__file__).parent


def run_full_pipeline(limit: int = 3, skip_download: bool = False, skip_transcribe: bool = False):
    """完整流程：下載 → 轉錄 → 分析"""

    episodes = []

    if not skip_download:
        print("=" * 50)
        print("步驟 1：抓取最新集數")
        print("=" * 50)
        from fetch_podcast import fetch_latest
        episodes = fetch_latest(limit=limit)
    else:
        print("[跳過] 下載步驟")
        # 從已有音檔建構假的 episodes 列表
        input_dir = Path(__file__).parent / "input"
        for mp3 in sorted(input_dir.glob("*.mp3"), key=lambda f: f.stat().st_mtime, reverse=True)[:limit]:
            episodes.append({
                "title": mp3.stem,
                "pub_date": "",
                "audio_url": "",
                "local_path": str(mp3),
            })

    if not skip_transcribe:
        print("\n" + "=" * 50)
        print("步驟 2：轉錄逐字稿")
        print("=" * 50)
        from transcribe import transcribe_episodes
        episodes = transcribe_episodes(episodes)
    else:
        print("[跳過] 轉錄步驟")
        # 嘗試找已有逐字稿
        transcripts_dir = OUTPUT_DIR / "transcripts"
        for ep in episodes:
            audio_path = Path(ep.get("local_path", ""))
            transcript = transcripts_dir / (audio_path.stem + ".txt")
            ep["transcript_path"] = str(transcript) if transcript.exists() else None

    print("\n" + "=" * 50)
    print("步驟 3：分析股票標的")
    print("=" * 50)
    from analyze import analyze_episodes
    results = analyze_episodes(episodes)

    print("\n" + "=" * 50)
    print("分析完成！")
    print("=" * 50)
    print_summary(results)

    return results


def run_single_transcript(transcript_path: str):
    """只分析單一逐字稿"""
    from analyze import analyze_transcript, format_report_markdown

    tp = Path(transcript_path)
    if not tp.exists():
        print(f"找不到檔案：{transcript_path}")
        return

    print(f"分析逐字稿：{tp.name}")
    report = analyze_transcript(tp, episode_title=tp.stem)

    md = format_report_markdown(report)
    print("\n" + md)

    md_path = REPORTS_DIR / (tp.stem + "_report.md")
    print(f"\n報告已存到：{md_path}")


def print_summary(results: list[dict]):
    """印出所有分析結果的摘要"""
    for ep in results:
        report = ep.get("report")
        if not report:
            print(f"  ✗ {ep.get('title', '未知')}（無報告）")
            continue

        title = report.get("episode_title", ep.get("title", "未知"))
        stocks = report.get("stocks", [])
        bullish = [s for s in stocks if s.get("stance") == "看多"]
        bearish = [s for s in stocks if s.get("stance") == "看空"]

        print(f"\n  ✓ {title}")
        print(f"    摘要：{report.get('summary', '')[:80]}...")
        if bullish:
            tickers = [s.get("ticker") or s.get("name") for s in bullish]
            print(f"    📈 看多：{', '.join(tickers)}")
        if bearish:
            tickers = [s.get("ticker") or s.get("name") for s in bearish]
            print(f"    📉 看空：{', '.join(tickers)}")

        report_md = ep.get("report_path")
        if report_md:
            print(f"    報告：{report_md}")


def main():
    parser = argparse.ArgumentParser(description="股癌 Podcast 分析工具")
    parser.add_argument("--limit", type=int, default=30, help="最多抓取集數（預設 30，配合 2026-01-01 起始日過濾）")
    parser.add_argument("--skip-download", action="store_true", help="跳過下載，使用已有音檔")
    parser.add_argument("--skip-transcribe", action="store_true", help="跳過轉錄，使用已有逐字稿")
    parser.add_argument("--transcript", type=str, help="直接分析指定逐字稿檔案路徑")
    args = parser.parse_args()

    print(f"股癌 Podcast 分析工具")
    print(f"執行時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print()

    if args.transcript:
        run_single_transcript(args.transcript)
    else:
        run_full_pipeline(
            limit=args.limit,
            skip_download=args.skip_download,
            skip_transcribe=args.skip_transcribe,
        )


if __name__ == "__main__":
    main()
