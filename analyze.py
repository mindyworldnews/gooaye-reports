"""
analyze.py
用 Claude API 分析股癌逐字稿，抽取提到的股票標的與類股
"""

import os
import json
import re
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(Path.home() / ".env")

OUTPUT_DIR = Path(__file__).parent / "output"
REPORTS_DIR = Path(__file__).parent

# 載入完整台股對照表（簡稱 → 代號），由 stock_lookup.json 產生
_STOCK_LOOKUP_PATH = REPORTS_DIR / "stock_lookup.json"
if _STOCK_LOOKUP_PATH.exists():
    with open(_STOCK_LOOKUP_PATH, encoding="utf-8") as _f:
        TW_STOCK_LOOKUP = json.load(_f)
else:
    TW_STOCK_LOOKUP = {}


def _build_tw_stock_table() -> str:
    """把 TW_STOCK_LOOKUP 轉成 prompt 用的緊湊對照表（每行 5 筆，按代號排序）"""
    if not TW_STOCK_LOOKUP:
        return "（stock_lookup.json 未找到，請先執行產生腳本）"
    pairs = sorted(TW_STOCK_LOOKUP.items(), key=lambda x: x[1])
    entries = [f"{name}={code}" for name, code in pairs]
    # 每行放 5 筆，用逗號分隔，大幅減少 token 用量
    rows = [", ".join(entries[i:i+5]) for i in range(0, len(entries), 5)]
    return "\n".join(rows)

# Whisper 常見聽錯詞對照表（錯誤轉錄 → 正確文字）
TRANSCRIPT_CORRECTIONS = {
    # 公司名稱
    "穩帽": "穩茂",
    "穩毛": "穩茂",
    "宅搬廠": "載板廠",
    "宅版廠": "載板廠",
    "載搬廠": "載板廠",
    "訊新": "訊芯",
    "真鼎": "臻鼎",
    "華邦典": "華邦電",
    "晶亨": "京元電",
    "桂冠": "矽谷",   # 視上下文
    "儲值": "處置",   # 股票被交易所列為處置股
    # 行業術語
    "CPO": "CPO",  # 避免被轉成 "西皮歐"
    "光通訊": "光通訊",
    "雞架": "基架",
    # 股癌常用說法
    "老黃": "老黃（黃仁勳/NVIDIA CEO）",
    "護國神山": "台積電（2330）",
    "小摩": "JP Morgan",
    "大摩": "Morgan Stanley",
    "高盛": "Goldman Sachs",
}


def fix_transcript(text: str) -> str:
    """修正 Whisper 常見聽錯詞"""
    for wrong, correct in TRANSCRIPT_CORRECTIONS.items():
        text = text.replace(wrong, correct)
    return text


ANALYZE_PROMPT = """你是一位熟悉台灣股市生態的專業分析助手，也熟悉股癌的說話風格。以下是股癌 Podcast 的逐字稿。

---

## 背景知識：股癌常提到的公司與術語

**台股公司代號完整對照表（名稱 → 代號）：**

{tw_stock_table}

**美股常見（股癌說法 → 公司/代號）：**
- 老黃、黃仁勳 → NVIDIA（NVDA）
- 微軟 → MSFT
- 美光 → Micron（MU）
- 超微 → AMD
- 高通 → Qualcomm（QCOM）
- 蘋果 → AAPL
- 特斯拉 → TSLA
- 馬維爾、Marvell → MRVL
- Cloudflare → NET
- Palantir → PLTR
- SpaceX → 未上市
- Broadcom → AVGO
- ASML → ASML
- 應材 → Applied Materials（AMAT）
- Lumentum → LITE（光通訊）
- Coherent → COHR（光通訊）
- Astera Labs → ALAB（光通訊）
- Applied Optoelectronics → AAOI（光通訊）
- CrowdStrike → CRWD（資安）
- Palo Alto Networks → PANW（資安）
- Salesforce → CRM（SaaS）
- Amazon → AMZN
- Meta → META
- ASTS（AST SpaceMobile）→ ASTS（低軌衛星）

**行業術語：**
- 載板廠 = ABF/BT基板製造商（如欣興3037、南電8046、景碩3189）
- 光通訊/光通 = 光纖通訊相關族群
- 散熱三雄 = 散熱相關龍頭廠商
- CPO = Co-Packaged Optics（共封裝光學）
- LPU = Liquid Processing Unit（NVIDIA新品）
- SMR = Small Modular Reactor（小型模組化反應爐）
- ASIC = 特定應用積體電路
- HBM = High Bandwidth Memory（高頻寬記憶體）
- CoWoP = Chip on Wafer on Package（封裝技術）
- eMMC = embedded MultiMediaCard（嵌入式快閃記憶體）
- AMR = 自主移動機器人
- TAM = 總可達市場規模
- 稼動率 = 設備利用率
- 左側交易 = 在趨勢確立前逆勢買進
- 右側交易 = 趨勢確立後順勢追漲
- 本夢比 = 用夢想/願景評估的本益比
- 汰調雜草灌溉鮮花/汰弱留強 = 賣弱股留強股的策略
- 國民制服股 = 散戶普遍持有的熱門股
- 梭哈/歐印 = 全倉押注，高風險集中投資
- 提款機 = 盤勢轉好時被大量賣出的股票
- 避風港 = 盤勢不佳時相對抗跌的股票

**注意：逐字稿由語音辨識產生，可能有聽錯的專有名詞，請根據上下文判斷正確意思。**
- 例：「宅搬廠」→「載板廠」、「穩帽」→「穩茂」、「訊新」→「訊芯」

---

## 任務一：抓出明確標的

找出股癌明確提到且有表達立場的個股、ETF、類股，以及總體經濟觀點。

**規則：**
- 只列有明確意見或特別強調的，隨口帶過的跳過
- 只提名字無任何觀點 → 立場標「僅提及」
- 台股代號：4-5位數字（2330、00878）
- 美股代號：英文大寫（NVDA、AAPL、SPY）
- 不確定代號 → ticker 填 null（**寧可填 null 也不要猜錯，錯誤代號比沒代號更糟**）
- 代號只能來自上方參考表或逐字稿中明確提到的數字，絕對不能自行推測

---

## 任務二：解讀模糊說法

股癌習慣用簡稱、綽號、行話，例如「光」「低軌」「那個做散熱的」「老黃家的」。

**請找出這集逐字稿中出現的這類說法，針對每一個：**

1. 引用原文（含前後文）
2. 根據**這集逐字稿的上下文**判斷他指的是什麼——如果這集他有提到客戶名稱、產品、地區、合約、競爭對手等線索，就用這些線索縮小範圍
3. 列出最相關的標的（最多5個，附代號）——候選必須和這集提到的線索吻合，不要只套通用知識
4. 說明你的推論是基於逐字稿的哪些線索，而不只是「這個詞通常指…」

**重要：如果這集沒有提到某個模糊說法，就不要列出來。每集的 vague_terms 應該反映這集實際說了什麼，不同集應該不一樣。**

---

請以 JSON 格式回傳，結構如下：

{
  "summary": "本集重點摘要（2-3句話）",
  "macro_views": [
    {
      "topic": "總體經濟主題",
      "view": "股癌的看法",
      "stance": "看多/看空/中立"
    }
  ],
  "stocks": [
    {
      "name": "標的名稱",
      "ticker": "股票代號或 null",
      "market": "US/TW/ETF/其他",
      "stance": "看多/看空/中立/僅提及",
      "reason": "股癌提到的原因或邏輯",
      "quote": "最相關原文片段，保留前後文讓人確認股癌確實有提到這個標的（100字以內）"
    }
  ],
  "sectors": [
    {
      "name": "類股名稱",
      "stance": "看多/看空/中立",
      "reason": "原因"
    }
  ],
  "vague_terms": [
    {
      "term": "股癌說的原話，例如：光、低軌、那個做散熱的",
      "interpretation": "這個說法最可能指的產業或主題",
      "stance": "看多/看空/中立/僅提及",
      "quote": "逐字稿原文脈絡（150字以內，必須包含完整前後文讓人確認股癌真的有提到這個說法）",
      "candidates": [
        {
          "name": "公司或ETF名稱",
          "ticker": "代號",
          "market": "US/TW",
          "reason": "這集逐字稿裡哪個線索讓你推斷是這檔（例如：股癌提到某客戶、某產品規格、某地區訂單）"
        }
      ]
    }
  ]
}

---
逐字稿內容：

{transcript}
"""


def get_claude_client():
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("找不到 ANTHROPIC_API_KEY，請確認 ~/.env 有設定")
    return anthropic.Anthropic(api_key=api_key)


def chunk_transcript(text: str, max_chars: int = 80000) -> list[str]:
    """
    如果逐字稿太長，切成多段（Claude context 限制）
    每段保留一點重疊避免斷句
    """
    if len(text) <= max_chars:
        return [text]

    chunks = []
    overlap = 500
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        # 盡量在句號處切割
        if end < len(text):
            cut = text.rfind("。", start + max_chars // 2, end)
            if cut > 0:
                end = cut + 1
        chunks.append(text[start:end])
        start = end - overlap

    return chunks


def analyze_transcript(transcript_path: Path, episode_title: str = "") -> dict:
    """
    分析單一逐字稿，回傳結構化的股票分析結果
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # 已分析過則直接讀取
    report_path = REPORTS_DIR / (transcript_path.stem + "_report.json")
    if report_path.exists():
        print(f"  [跳過] 已有分析報告：{report_path.name}")
        with open(report_path, encoding="utf-8") as f:
            return json.load(f)

    print(f"  [分析] {transcript_path.name}")
    with open(transcript_path, encoding="utf-8") as f:
        transcript = f.read()

    transcript = fix_transcript(transcript)
    print(f"         逐字稿長度：{len(transcript)} 字")

    client = get_claude_client()
    chunks = chunk_transcript(transcript)

    if len(chunks) == 1:
        result = _analyze_single_chunk(client, chunks[0])
    else:
        print(f"         逐字稿較長，分 {len(chunks)} 段分析後合併...")
        result = _analyze_multiple_chunks(client, chunks)

    # 加上 metadata
    result["episode_title"] = episode_title or transcript_path.stem
    result["analyzed_at"] = datetime.now().isoformat()
    result["transcript_chars"] = len(transcript)

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"         完成！找到 {len(result.get('stocks', []))} 個股票標的")
    return result


def _analyze_single_chunk(client, transcript: str) -> dict:
    prompt = ANALYZE_PROMPT.replace("{tw_stock_table}", _build_tw_stock_table())
    prompt = prompt.replace("{transcript}", transcript)

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=16384,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text

    # 抽取 JSON（可能有前後文字）
    json_match = re.search(r'\{[\s\S]*\}', raw)
    if not json_match:
        raise ValueError(f"Claude 回傳的內容沒有有效 JSON:\n{raw[:500]}")

    json_str = json_match.group()
    # 清除 trailing comma（Claude 有時會回傳不合法的 JSON）
    json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
    return json.loads(json_str)


def _analyze_multiple_chunks(client, chunks: list[str]) -> dict:
    """分段分析後，再請 Claude 合併結果"""
    partial_results = []
    for i, chunk in enumerate(chunks):
        print(f"         分析第 {i+1}/{len(chunks)} 段...")
        try:
            result = _analyze_single_chunk(client, chunk)
            partial_results.append(result)
        except Exception as e:
            print(f"         第 {i+1} 段分析失敗：{e}")

    if not partial_results:
        raise ValueError("所有分段都分析失敗")

    # 合併：stocks 去重（同 ticker 的保留 stance 最強的）
    merged = {
        "summary": partial_results[0].get("summary", ""),
        "macro_views": [],
        "stocks": [],
        "sectors": [],
        "key_timestamps": "",
    }

    seen_tickers = {}
    for part in partial_results:
        merged["macro_views"].extend(part.get("macro_views", []))
        merged["sectors"].extend(part.get("sectors", []))

        for stock in part.get("stocks", []):
            ticker = stock.get("ticker") or stock.get("name")
            if ticker not in seen_tickers:
                seen_tickers[ticker] = stock
                merged["stocks"].append(stock)

    return merged


def format_report_html(report: dict) -> str:
    """產出手機友善的自含式 HTML 報告"""
    import html as html_mod

    def esc(s):
        return html_mod.escape(str(s or ""))

    def chart_link(ticker, market):
        """產生 Yahoo Finance K線連結"""
        if not ticker:
            return ""
        t = ticker.strip().upper()
        if market in ("TW", "ETF") and t[0].isdigit():
            url = f"https://tw.stock.yahoo.com/quote/{t}"
        else:
            url = f"https://finance.yahoo.com/quote/{t}"
        return (
            f'<a href="{url}" target="_blank" title="開啟 {t} K線圖" class="chart-btn">'
            f'<svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14">'
            f'<rect x="2" y="10" width="3" height="8" rx="1"/>'
            f'<rect x="8.5" y="5" width="3" height="13" rx="1"/>'
            f'<rect x="15" y="2" width="3" height="16" rx="1"/>'
            f'</svg></a>'
        )

    title = report.get("episode_title", "未知集數")
    date = report.get("analyzed_at", "")[:10]
    summary = report.get("summary", "")
    stocks = report.get("stocks", [])
    sectors = report.get("sectors", [])
    macro = report.get("macro_views", [])
    vague_terms = report.get("vague_terms", [])

    STANCE_META = {
        "看多": ("bullish",  "📈", "看多"),
        "看空": ("bearish",  "📉", "看空"),
        "中立": ("neutral",  "➡️", "中立"),
        "僅提及": ("mention", "💬", "僅提及"),
    }

    def stance_badge(stance):
        cls, emoji, label = STANCE_META.get(stance, ("mention", "💬", stance))
        return f'<span class="badge {cls}">{emoji} {esc(label)}</span>'

    def stock_cards(stock_list):
        if not stock_list:
            return "<p class='empty'>本集無個股標的</p>"
        cards = []
        for s in stock_list:
            stance = s.get("stance", "")
            cls, _, _ = STANCE_META.get(stance, ("mention", "", ""))
            ticker = s.get("ticker") or ""
            market = s.get("market") or ""
            name = esc(s.get("name", ""))
            reason = esc(s.get("reason", ""))
            quote = esc(s.get("quote", ""))
            cl = chart_link(ticker, market)
            ticker_html = (
                f'<code class="ticker">{esc(ticker)}</code>{cl}' if ticker else ""
            )
            market_tag = f'<span class="market-tag">{esc(market)}</span>' if market else ""
            quote_html = f'<blockquote>「{quote}」</blockquote>' if quote else ""
            wl_btn = (
                f'<button class="wl-btn" data-ticker="{esc(ticker)}" '
                f'data-name="{name}" data-market="{esc(market)}" title="加入自選股">⭐</button>'
                if ticker else ""
            )
            cards.append(f"""
        <div class="card {cls}" data-ticker="{esc(ticker)}" data-name="{name}" data-market="{esc(market)}">
          <div class="card-header">
            <span class="stock-name">{name}</span>
            <span class="card-meta">{ticker_html}{market_tag}{wl_btn}</span>
          </div>
          {stance_badge(stance)}
          <p class="reason">{reason}</p>
          {quote_html}
        </div>""")
        return "\n".join(cards)

    def macro_rows(macro_list):
        if not macro_list:
            return ""
        rows = []
        for m in macro_list:
            rows.append(f"""
        <div class="macro-row">
          <div class="macro-topic">{esc(m.get('topic',''))}</div>
          <div>{stance_badge(m.get('stance',''))}<span class="macro-view"> {esc(m.get('view',''))}</span></div>
        </div>""")
        return "\n".join(rows)

    def sector_chips(sector_list):
        if not sector_list:
            return ""
        chips = []
        for sec in sector_list:
            cls, _, _ = STANCE_META.get(sec.get("stance",""), ("mention","",""))
            chips.append(
                f'<div class="sector-chip {cls}">'
                f'{stance_badge(sec.get("stance",""))}'
                f' <strong>{esc(sec.get("name",""))}</strong>'
                f'<span class="sector-reason"> — {esc(sec.get("reason",""))}</span>'
                f'</div>'
            )
        return "\n".join(chips)

    def vague_cards(terms):
        if not terms:
            return ""
        cards = []
        for t in terms:
            stance = t.get("stance", "")
            cls, _, _ = STANCE_META.get(stance, ("mention", "", ""))
            term = esc(t.get("term", ""))
            interp = esc(t.get("interpretation", ""))
            quote = esc(t.get("quote", ""))
            quote_html = f'<blockquote>「{quote}」</blockquote>' if quote else ""
            candidates = t.get("candidates", [])
            cand_html = ""
            if candidates:
                rows = []
                for c in candidates:
                    tk_raw = c.get("ticker") or ""
                    tk = esc(tk_raw)
                    mkt = c.get("market", "")
                    cl = chart_link(tk_raw, mkt)
                    tk_tag = f'<code class="ticker">{tk}</code>{cl} ' if tk else ""
                    mkt_tag = f'<span class="market-tag">{esc(mkt)}</span> ' if mkt else ""
                    cand_name = esc(c.get("name", ""))
                    wl_btn_sm = (
                        f'<button class="wl-btn wl-btn-sm" data-ticker="{tk}" '
                        f'data-name="{cand_name}" data-market="{esc(mkt)}" title="加入自選股">⭐</button>'
                        if tk_raw else ""
                    )
                    rows.append(
                        f'<div class="cand-row" data-cand-ticker="{tk}" '
                        f'data-cand-name="{cand_name}" data-cand-market="{esc(mkt)}">'
                        f'{tk_tag}{mkt_tag}'
                        f'<span class="cand-name">{cand_name}</span>'
                        f'<span class="cand-reason"> — {esc(c.get("reason",""))}</span>'
                        f'{wl_btn_sm}'
                        f'</div>'
                    )
                cand_html = '<div class="cand-list">' + "".join(rows) + '</div>'
            cards.append(f"""
        <div class="vague-card {cls}">
          <div class="vague-header">
            <span class="vague-term">「{term}」</span>
            {stance_badge(stance)}
          </div>
          <p class="vague-interp">{interp}</p>
          {quote_html}
          {cand_html}
        </div>""")
        return "\n".join(cards)

    # 只列看多/看空的股票做「快速清單」
    quick = [s for s in stocks if s.get("stance") in ("看多", "看空")]
    # vague_terms 裡看多/看空的候選也加進快速清單
    for t in vague_terms:
        if t.get("stance") in ("看多", "看空"):
            for c in t.get("candidates", []):
                c["_from_vague"] = t.get("term", "")
                quick.append({
                    "ticker": c.get("ticker") or c.get("name"),
                    "name": c.get("name"),
                    "stance": t.get("stance"),
                    "_vague": True,
                })

    quick_html = ""
    if quick:
        items = []
        seen_quick = set()
        for s in quick:
            cls = "bullish" if s.get("stance") == "看多" else "bearish"
            if s.get("_vague"):
                cls = "vague"
            ticker = s.get("ticker") or s.get("name", "")
            if ticker in seen_quick:
                continue
            seen_quick.add(ticker)
            items.append(f'<span class="quick-tag {cls}">{esc(ticker)}</span>')
        quick_html = f'<div class="quick-bar">{"".join(items)}</div>'

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>股癌 {esc(title)}</title>
<style>
  :root {{
    --green: #16a34a; --green-bg: #f0fdf4; --green-border: #bbf7d0;
    --red: #dc2626;   --red-bg: #fef2f2;   --red-border: #fecaca;
    --gray: #6b7280;  --gray-bg: #f9fafb;  --gray-border: #e5e7eb;
    --blue: #2563eb;  --radius: 12px; --font: -apple-system, "Noto Sans TC", sans-serif;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: var(--font); background: #f3f4f6; color: #111827; font-size: 16px; line-height: 1.6; }}
  .container {{ max-width: 680px; margin: 0 auto; padding: 16px; }}

  /* Header */
  .header {{ background: #111827; color: #fff; border-radius: var(--radius); padding: 20px; margin-bottom: 16px; }}
  .header h1 {{ font-size: 1.25rem; font-weight: 700; margin-bottom: 4px; }}
  .header .meta {{ font-size: 0.8rem; color: #9ca3af; }}

  /* Summary */
  .summary-box {{ background: #fff; border-radius: var(--radius); padding: 16px; margin-bottom: 16px;
                  border-left: 4px solid #2563eb; }}
  .summary-box p {{ color: #374151; font-size: 0.95rem; }}

  /* Quick bar */
  .quick-bar {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }}
  .quick-tag {{ padding: 6px 12px; border-radius: 20px; font-size: 0.85rem; font-weight: 600; }}
  .quick-tag.bullish {{ background: var(--green-bg); color: var(--green); border: 1px solid var(--green-border); }}
  .quick-tag.bearish {{ background: var(--red-bg);   color: var(--red);   border: 1px solid var(--red-border); }}

  /* Section title */
  .section-title {{ font-size: 0.75rem; font-weight: 700; text-transform: uppercase;
                    letter-spacing: .08em; color: #6b7280; margin: 20px 0 10px; }}

  /* Stock cards */
  .card {{ background: #fff; border-radius: var(--radius); padding: 14px 16px; margin-bottom: 10px;
           border-left: 4px solid #e5e7eb; }}
  .card.bullish {{ border-left-color: var(--green); }}
  .card.bearish {{ border-left-color: var(--red); }}
  .card.neutral {{ border-left-color: #d1d5db; }}
  .card.mention {{ border-left-color: #e5e7eb; }}
  .card-header {{ display: flex; justify-content: space-between; align-items: flex-start;
                  margin-bottom: 6px; gap: 8px; }}
  .stock-name {{ font-weight: 700; font-size: 1rem; }}
  .card-meta {{ display: flex; gap: 4px; align-items: center; flex-shrink: 0; }}
  code.ticker {{ background: #1e293b; color: #e2e8f0; font-size: 0.8rem;
                 padding: 2px 7px; border-radius: 6px; font-family: monospace; }}
  a.chart-btn {{ display: inline-flex; align-items: center; justify-content: center;
                 width: 22px; height: 22px; border-radius: 5px; margin-left: 4px;
                 background: #e0f2fe; color: #0369a1; vertical-align: middle;
                 text-decoration: none; transition: background 0.15s; }}
  a.chart-btn:hover {{ background: #bae6fd; }}
  .market-tag {{ background: #e0e7ff; color: #3730a3; font-size: 0.75rem;
                 padding: 2px 6px; border-radius: 6px; }}
  .reason {{ font-size: 0.9rem; color: #374151; margin-top: 6px; }}
  blockquote {{ font-size: 0.82rem; color: #6b7280; margin-top: 6px;
                padding-left: 10px; border-left: 2px solid #d1d5db; font-style: italic; }}
  .empty {{ color: #9ca3af; font-size: 0.9rem; text-align: center; padding: 16px; }}

  /* Badge */
  .badge {{ display: inline-block; font-size: 0.78rem; font-weight: 600;
            padding: 2px 8px; border-radius: 20px; }}
  .badge.bullish {{ background: var(--green-bg); color: var(--green); }}
  .badge.bearish {{ background: var(--red-bg);   color: var(--red); }}
  .badge.neutral {{ background: var(--gray-bg);  color: var(--gray); }}
  .badge.mention {{ background: #eff6ff; color: var(--blue); }}

  /* Macro */
  .macro-row {{ background: #fff; border-radius: var(--radius); padding: 12px 14px;
                margin-bottom: 8px; }}
  .macro-topic {{ font-weight: 600; font-size: 0.9rem; margin-bottom: 4px; }}
  .macro-view {{ font-size: 0.88rem; color: #374151; }}

  /* Sectors */
  .sector-chip {{ background: #fff; border-radius: var(--radius); padding: 10px 14px;
                  margin-bottom: 8px; font-size: 0.88rem; }}
  .sector-reason {{ color: #6b7280; }}

  /* Vague terms */
  .vague-card {{ background: #fff; border-radius: var(--radius); padding: 14px 16px;
                 margin-bottom: 10px; border-left: 4px solid #a78bfa; }}
  .vague-card.bullish {{ border-left-color: var(--green); }}
  .vague-card.bearish {{ border-left-color: var(--red); }}
  .vague-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; flex-wrap: wrap; }}
  .vague-term {{ font-weight: 700; font-size: 1rem; color: #111827; }}
  .vague-interp {{ font-size: 0.88rem; color: #374151; margin-bottom: 6px; }}
  .cand-list {{ margin-top: 10px; display: flex; flex-direction: column; gap: 6px; }}
  .cand-row {{ font-size: 0.85rem; display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px;
               padding: 6px 10px; background: #f8fafc; border-radius: 8px; }}
  .cand-name {{ font-weight: 600; }}
  .cand-reason {{ color: #6b7280; }}
  .quick-tag.vague {{ background: #f5f3ff; color: #7c3aed; border: 1px solid #ddd6fe; }}
  .wl-btn {{ background: none; border: none; cursor: pointer; font-size: 1rem;
             padding: 0 2px; line-height: 1; opacity: 0.5; transition: opacity 0.15s; }}
  .wl-btn:hover {{ opacity: 1; }}
  .wl-btn.active {{ opacity: 1; }}
  .wl-btn-sm {{ font-size: 0.8rem; margin-left: 4px; }}

  /* Footer */
  .footer {{ text-align: center; font-size: 0.75rem; color: #9ca3af; padding: 24px 0 8px; }}
</style>
</head>
<body>
<div class="container">

  <div class="header">
    <div class="meta">股癌 Podcast 分析報告 · {esc(date)}</div>
    <h1>{esc(title)}</h1>
  </div>

  {"<div class='summary-box'><p>" + esc(summary) + "</p></div>" if summary else ""}

  {quick_html}

  {"<div class='section-title'>🔍 詞彙解讀（股癌說的「光」「低軌」是指…）</div>" + vague_cards(vague_terms) if vague_terms else ""}

  {"<div class='section-title'>個股標的</div>" + stock_cards(stocks) if stocks else ""}

  {"<div class='section-title'>類股 / 產業</div>" + sector_chips(sectors) if sectors else ""}

  {"<div class='section-title'>總體經濟觀點</div>" + macro_rows(macro) if macro else ""}

  <div class="footer">由 Claude 自動分析 · 僅供參考，非投資建議</div>
</div>
</body>
</html>"""


def analyze_episodes(episodes: list[dict]) -> list[dict]:
    """
    批次分析，episodes 是 transcribe 的輸出格式
    """
    results = []
    for ep in episodes:
        transcript_path = ep.get("transcript_path")
        if not transcript_path:
            print(f"[跳過分析] {ep['title']}（無逐字稿）")
            results.append({**ep, "report": None})
            continue

        tp = Path(transcript_path)
        if not tp.exists():
            print(f"[找不到逐字稿] {tp}")
            results.append({**ep, "report": None})
            continue

        print(f"\n集數：{ep['title']}")
        report = analyze_transcript(tp, episode_title=ep["title"])

        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        html_path = REPORTS_DIR / (tp.stem + "_report.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(format_report_html(report))

        results.append({**ep, "report": report, "report_path": str(html_path)})

    # 每次分析後重新產生 index.html
    try:
        idx = generate_index_html(REPORTS_DIR)
        print(f"\n主頁面：{idx}")
    except Exception as e:
        print(f"[警告] index.html 產生失敗：{e}")

    # 自動 push 到 GitHub Pages
    git_push_reports(REPORTS_DIR)

    return results


def git_push_reports(reports_dir: Path):
    """將報告資料夾 push 到 GitHub Pages"""
    import subprocess
    git = reports_dir / ".git"
    if not git.exists():
        print("[跳過] 報告資料夾尚未初始化 git，請先執行 setup_git.sh")
        return
    try:
        from datetime import datetime
        msg = f"update reports {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        subprocess.run(["git", "-C", str(reports_dir), "add", "-A"], check=True)
        result = subprocess.run(
            ["git", "-C", str(reports_dir), "diff", "--cached", "--quiet"]
        )
        if result.returncode == 0:
            print("[git] 無新變更，跳過 push")
            return
        subprocess.run(["git", "-C", str(reports_dir), "commit", "-m", msg], check=True)
        subprocess.run(["git", "-C", str(reports_dir), "push"], check=True)
        print(f"[git] 已 push：{msg}")
    except subprocess.CalledProcessError as e:
        print(f"[警告] git push 失敗：{e}")


def generate_index_html(reports_dir: Path) -> Path:
    """
    讀取 reports_dir 內所有 *_report.json，
    產生帶有左側選集選單 + 自選股功能的 index.html。
    """
    import html as html_mod

    # 讀取所有報告，按日期降冪排列
    reports = []
    for f in sorted(reports_dir.glob("*_report.json"), reverse=True):
        try:
            with open(f, encoding="utf-8") as fh:
                r = json.load(fh)
            r["_json_stem"] = f.stem  # e.g. "EP647___report"
            reports.append(r)
        except Exception:
            continue

    if not reports:
        raise ValueError("股癌分析器資料夾內沒有 JSON 報告")

    def esc(s):
        return html_mod.escape(str(s or ""))

    def chart_url_js():
        # JS 版的 chart url helper（嵌入 index.html）
        return """
function chartUrl(ticker, market) {
  if (!ticker) return '#';
  const t = ticker.toUpperCase();
  if ((market === 'TW' || market === 'ETF') && /^\\d/.test(t))
    return 'https://tw.stock.yahoo.com/quote/' + t;
  return 'https://finance.yahoo.com/quote/' + t;
}"""

    # 產生每集的 HTML 內容片段（重用 format_report_html 的內容區段）
    # 直接把個別 HTML 檔案的 body 內容嵌入
    ep_data = []
    for r in reports:
        title = r.get("episode_title", r["_json_stem"])
        date = r.get("analyzed_at", "")[:10]
        ep_id = r["_json_stem"].replace("_report", "")

        # 讀已產生的 HTML 檔案，抽取 <div class="container"> 內容
        html_file = reports_dir / (r["_json_stem"] + ".html")
        if html_file.exists():
            raw = html_file.read_text(encoding="utf-8")
            # 抽取 container div 的內容
            m = re.search(r'<div class="container">([\s\S]*?)</div>\s*</body>', raw)
            body_html = m.group(1).strip() if m else f"<p>{esc(title)}</p>"
        else:
            body_html = f"<p>尚未產生報告</p>"

        # JSON-encode 後嵌入 JS（處理引號、換行等特殊字元）
        ep_data.append({
            "id": ep_id,
            "title": title,
            "date": date,
            "html": body_html,
        })

    # 產生 sidebar 的集數列表
    ep_list_html = ""
    for ep in ep_data:
        ep_list_html += (
            f'<div class="ep-item" id="nav-{esc(ep["id"])}" '
            f'onclick="showEpisode(\'{esc(ep["id"])}\')">'
            f'<div class="ep-date">{esc(ep["date"])}</div>'
            f'<div class="ep-title">{esc(ep["title"])}</div>'
            f'</div>\n'
        )

    # 把 ep_data 的 html 欄位 JSON-encode 成 JS 字串
    ep_js = json.dumps(
        [{"id": e["id"], "title": e["title"], "date": e["date"], "html": e["html"]}
         for e in ep_data],
        ensure_ascii=False
    )

    first_id = ep_data[0]["id"] if ep_data else ""

    index_html = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>股癌分析器</title>
<style>
:root {{
  --green:#16a34a;--green-bg:#f0fdf4;--green-border:#bbf7d0;
  --red:#dc2626;--red-bg:#fef2f2;--red-border:#fecaca;
  --gray:#6b7280;--gray-bg:#f9fafb;
  --blue:#2563eb;--radius:12px;
  --font:-apple-system,"Noto Sans TC",sans-serif;
  --sidebar:270px;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:var(--font);background:#f3f4f6;color:#111827;font-size:16px;line-height:1.6;display:flex;height:100dvh;overflow:hidden}}

/* ── Sidebar ── */
#sidebar{{width:var(--sidebar);flex-shrink:0;background:#1e293b;color:#f1f5f9;display:flex;flex-direction:column;height:100dvh;overflow:hidden;transition:transform .25s;z-index:200}}
#sidebar-header{{padding:16px;font-weight:700;font-size:1rem;border-bottom:1px solid #334155;flex-shrink:0}}
.tab-bar{{display:flex;border-bottom:1px solid #334155;flex-shrink:0}}
.tab{{flex:1;padding:10px;background:none;border:none;color:#94a3b8;font-size:0.85rem;cursor:pointer;font-weight:600}}
.tab.active{{color:#f1f5f9;border-bottom:2px solid #38bdf8}}
#tab-episodes{{overflow-y:auto;flex:1}}
#tab-watchlist{{overflow-y:auto;flex:1;display:none;padding:8px}}
.ep-item{{padding:12px 16px;cursor:pointer;border-bottom:1px solid #334155;transition:background .15s}}
.ep-item:hover,.ep-item.active{{background:#334155}}
.ep-date{{font-size:0.72rem;color:#94a3b8;margin-bottom:2px}}
.ep-title{{font-size:0.88rem;font-weight:500;line-height:1.3}}

/* ── Watchlist ── */
.wl-item{{background:#334155;border-radius:10px;padding:12px;margin-bottom:8px}}
.wl-top{{display:flex;align-items:center;gap:6px;margin-bottom:4px}}
.wl-name{{font-size:0.85rem;color:#cbd5e1;margin-bottom:2px}}
.wl-from{{font-size:0.72rem;color:#64748b}}
.wl-remove{{margin-top:6px;background:none;border:1px solid #475569;color:#94a3b8;border-radius:6px;padding:2px 8px;font-size:0.75rem;cursor:pointer}}
.wl-remove:hover{{background:#475569}}
.wl-empty{{color:#64748b;font-size:0.85rem;text-align:center;padding:24px 8px}}

/* ── Overlay (mobile) ── */
#overlay{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:100}}

/* ── Main ── */
#main{{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0}}
#topbar{{background:#fff;border-bottom:1px solid #e5e7eb;padding:10px 16px;display:flex;align-items:center;gap:12px;flex-shrink:0}}
#hamburger{{background:none;border:none;font-size:1.3rem;cursor:pointer;display:none;color:#374151}}
#current-title{{font-size:0.95rem;font-weight:600;color:#111827;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
#content{{flex:1;overflow-y:auto;padding:16px}}
#content .container{{max-width:680px;margin:0 auto}}

/* ── Episode content styles (copied from standalone) ── */
.header{{background:#111827;color:#fff;border-radius:var(--radius);padding:20px;margin-bottom:16px}}
.header h1{{font-size:1.25rem;font-weight:700;margin-bottom:4px}}
.header .meta{{font-size:0.8rem;color:#9ca3af}}
.summary-box{{background:#fff;border-radius:var(--radius);padding:16px;margin-bottom:16px;border-left:4px solid #2563eb}}
.summary-box p{{color:#374151;font-size:0.95rem}}
.quick-bar{{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px}}
.quick-tag{{padding:6px 12px;border-radius:20px;font-size:0.85rem;font-weight:600}}
.quick-tag.bullish{{background:var(--green-bg);color:var(--green);border:1px solid var(--green-border)}}
.quick-tag.bearish{{background:var(--red-bg);color:var(--red);border:1px solid var(--red-border)}}
.quick-tag.vague{{background:#f5f3ff;color:#7c3aed;border:1px solid #ddd6fe}}
.section-title{{font-size:0.75rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#6b7280;margin:20px 0 10px}}
.card{{background:#fff;border-radius:var(--radius);padding:14px 16px;margin-bottom:10px;border-left:4px solid #e5e7eb}}
.card.bullish{{border-left-color:var(--green)}}
.card.bearish{{border-left-color:var(--red)}}
.card.neutral{{border-left-color:#d1d5db}}
.card-header{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px;gap:8px}}
.stock-name{{font-weight:700;font-size:1rem}}
.card-meta{{display:flex;gap:4px;align-items:center;flex-shrink:0;flex-wrap:wrap}}
code.ticker{{background:#1e293b;color:#e2e8f0;font-size:0.8rem;padding:2px 7px;border-radius:6px;font-family:monospace}}
a.chart-btn{{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:5px;margin-left:4px;background:#e0f2fe;color:#0369a1;vertical-align:middle;text-decoration:none}}
a.chart-btn:hover{{background:#bae6fd}}
.market-tag{{background:#e0e7ff;color:#3730a3;font-size:0.75rem;padding:2px 6px;border-radius:6px}}
.reason{{font-size:0.9rem;color:#374151;margin-top:6px}}
blockquote{{font-size:0.82rem;color:#6b7280;margin-top:6px;padding-left:10px;border-left:2px solid #d1d5db;font-style:italic}}
.empty{{color:#9ca3af;font-size:0.9rem;text-align:center;padding:16px}}
.badge{{display:inline-block;font-size:0.78rem;font-weight:600;padding:2px 8px;border-radius:20px}}
.badge.bullish{{background:var(--green-bg);color:var(--green)}}
.badge.bearish{{background:var(--red-bg);color:var(--red)}}
.badge.neutral{{background:var(--gray-bg);color:var(--gray)}}
.badge.mention{{background:#eff6ff;color:var(--blue)}}
.macro-row{{background:#fff;border-radius:var(--radius);padding:12px 14px;margin-bottom:8px}}
.macro-topic{{font-weight:600;font-size:0.9rem;margin-bottom:4px}}
.macro-view{{font-size:0.88rem;color:#374151}}
.sector-chip{{background:#fff;border-radius:var(--radius);padding:10px 14px;margin-bottom:8px;font-size:0.88rem}}
.sector-reason{{color:#6b7280}}
.vague-card{{background:#fff;border-radius:var(--radius);padding:14px 16px;margin-bottom:10px;border-left:4px solid #a78bfa}}
.vague-card.bullish{{border-left-color:var(--green)}}
.vague-card.bearish{{border-left-color:var(--red)}}
.vague-header{{display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap}}
.vague-term{{font-weight:700;font-size:1rem;color:#111827}}
.vague-interp{{font-size:0.88rem;color:#374151;margin-bottom:6px}}
.cand-list{{margin-top:10px;display:flex;flex-direction:column;gap:6px}}
.cand-row{{font-size:0.85rem;display:flex;flex-wrap:wrap;align-items:baseline;gap:4px;padding:6px 10px;background:#f8fafc;border-radius:8px}}
.cand-name{{font-weight:600}}
.cand-reason{{color:#6b7280}}
.wl-btn{{background:none;border:none;cursor:pointer;font-size:1rem;padding:0 2px;line-height:1;opacity:.5;transition:opacity .15s}}
.wl-btn:hover,.wl-btn.in-wl{{opacity:1}}
.wl-btn-sm{{font-size:0.8rem;margin-left:4px}}
.footer{{text-align:center;font-size:0.75rem;color:#9ca3af;padding:24px 0 8px}}

/* ── Mobile ── */
@media(max-width:700px){{
  #sidebar{{position:fixed;left:0;top:0;height:100dvh;transform:translateX(-100%)}}
  #sidebar.open{{transform:translateX(0)}}
  #overlay.show{{display:block}}
  #hamburger{{display:block}}
  #main{{width:100%}}
}}
</style>
</head>
<body>

<div id="sidebar">
  <div id="sidebar-header">📊 股癌分析器</div>
  <div class="tab-bar">
    <button class="tab active" onclick="switchTab('episodes')">集數</button>
    <button class="tab" onclick="switchTab('watchlist')">⭐ 自選股</button>
  </div>
  <div id="tab-episodes">
{ep_list_html}
  </div>
  <div id="tab-watchlist"></div>
</div>

<div id="overlay" onclick="toggleSidebar()"></div>

<div id="main">
  <div id="topbar">
    <button id="hamburger" onclick="toggleSidebar()">☰</button>
    <span id="current-title">股癌分析器</span>
  </div>
  <div id="content"><div class="container"></div></div>
</div>

<script>
const EPISODES = {ep_js};

{chart_url_js()}

function showEpisode(id) {{
  const ep = EPISODES.find(e => e.id === id);
  if (!ep) return;
  document.getElementById('content').innerHTML = '<div class="container">' + ep.html + '</div>';
  document.getElementById('current-title').textContent = ep.title;
  document.querySelectorAll('.ep-item').forEach(el => el.classList.remove('active'));
  const nav = document.getElementById('nav-' + id);
  if (nav) nav.classList.add('active');
  // 加上自選股按鈕的事件
  document.querySelectorAll('.wl-btn').forEach(btn => {{
    btn.onclick = function() {{
      const t = this.dataset.ticker, n = this.dataset.name, m = this.dataset.market;
      if (!t) return;
      if (isInWatchlist(t)) {{
        removeFromWatchlist(t);
        this.textContent = '⭐';
        this.classList.remove('in-wl');
      }} else {{
        addToWatchlist(t, n, m, ep.title);
        this.textContent = '✅';
        this.classList.add('in-wl');
      }}
    }};
    if (isInWatchlist(btn.dataset.ticker)) {{
      btn.textContent = '✅';
      btn.classList.add('in-wl');
    }}
  }});
  // 關閉手機側欄
  if (window.innerWidth <= 700) toggleSidebar(false);
}}

function isInWatchlist(ticker) {{
  if (!ticker) return false;
  return getWatchlist().some(w => w.ticker === ticker);
}}

function getWatchlist() {{
  return JSON.parse(localStorage.getItem('gooaye_wl') || '[]');
}}

function addToWatchlist(ticker, name, market, fromEpisode) {{
  const wl = getWatchlist();
  if (!wl.find(w => w.ticker === ticker)) {{
    wl.push({{ticker, name, market, fromEpisode, addedAt: new Date().toISOString().slice(0,10)}});
    localStorage.setItem('gooaye_wl', JSON.stringify(wl));
    renderWatchlist();
  }}
}}

function removeFromWatchlist(ticker) {{
  const wl = getWatchlist().filter(w => w.ticker !== ticker);
  localStorage.setItem('gooaye_wl', JSON.stringify(wl));
  renderWatchlist();
  // 同步更新當前頁面的按鈕狀態
  document.querySelectorAll('.wl-btn').forEach(btn => {{
    if (btn.dataset.ticker === ticker) {{
      btn.textContent = '⭐';
      btn.classList.remove('in-wl');
    }}
  }});
}}

function renderWatchlist() {{
  const wl = getWatchlist();
  const el = document.getElementById('tab-watchlist');
  if (!wl.length) {{
    el.innerHTML = '<p class="wl-empty">點擊報告中的 ⭐ 加入自選股</p>';
    return;
  }}
  el.innerHTML = wl.map(w => `
    <div class="wl-item">
      <div class="wl-top">
        <code class="ticker">${{w.ticker}}</code>
        <span class="market-tag">${{w.market}}</span>
        <a href="${{chartUrl(w.ticker, w.market)}}" target="_blank" class="chart-btn" title="看K線">
          <svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14">
            <rect x="2" y="10" width="3" height="8" rx="1"/>
            <rect x="8.5" y="5" width="3" height="13" rx="1"/>
            <rect x="15" y="2" width="3" height="16" rx="1"/>
          </svg>
        </a>
      </div>
      <div class="wl-name">${{w.name}}</div>
      <div class="wl-from">來自 ${{w.fromEpisode}} · 加入 ${{w.addedAt}}</div>
      <button class="wl-remove" onclick="removeFromWatchlist('${{w.ticker}}')">✕ 移除</button>
    </div>
  `).join('');
}}

function switchTab(tab) {{
  document.getElementById('tab-episodes').style.display = tab === 'episodes' ? '' : 'none';
  document.getElementById('tab-watchlist').style.display = tab === 'watchlist' ? '' : 'none';
  document.querySelectorAll('.tab').forEach((t, i) => {{
    t.classList.toggle('active', (i === 0) === (tab === 'episodes'));
  }});
  if (tab === 'watchlist') renderWatchlist();
}}

function toggleSidebar(force) {{
  const sb = document.getElementById('sidebar');
  const ov = document.getElementById('overlay');
  const open = force !== undefined ? force : !sb.classList.contains('open');
  sb.classList.toggle('open', open);
  ov.classList.toggle('show', open);
}}

// 初始化
showEpisode('{first_id}');
renderWatchlist();
</script>
</body>
</html>"""

    index_path = reports_dir / "index.html"
    index_path.write_text(index_html, encoding="utf-8")
    return index_path


if __name__ == "__main__":
    # 重新產生 index.html（用既有的 JSON 報告）
    idx = generate_index_html(REPORTS_DIR)
    print(f"產生：{idx}")
